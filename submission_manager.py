"""
submission_manager.py

Handles the song submission workflow:
- Detects Spotify links posted in #song-submissions
- Routes trusted players to auto-approval
- Routes regular players to #pending-approval for mod review
- Polls for ✅/❌ reactions and processes decisions
- Posts rejection reasons back to submitters
- Adds approved songs to the Spotify playlist

Environment variables required:
  SUBMISSIONS_CHANNEL_ID   - #song-submissions channel ID
  PENDING_CHANNEL_ID       - #pending-approval channel ID (mod-only)
  TRUSTED_ROLE_ID          - Discord role ID for trusted players
  APPROVER_DISCORD_ID      - Discord ID of the mod who approves (you)
"""

import json
import logging
import os
import re
import time

import requests

from discord_client import DiscordError

log = logging.getLogger("submissions")

DISCORD_API = "https://discord.com/api/v10"

# How far back to look for new submissions and pending reactions (seconds)
SUBMISSION_LOOKBACK = 3600  # look back 1 hour to catch submissions after restarts
REACTION_POLL_AGE   = 86400 * 7  # keep polling pending messages for up to 7 days

SPOTIFY_TRACK_RE = re.compile(
    r"https?://open\.spotify\.com/track/([A-Za-z0-9]+)"
)


class SubmissionManager:
    def __init__(
        self,
        bot_token,
        spotify_client,
        discord_client,
        user_lookup,
        playlist_id,
    ):
        self.bot_token       = bot_token
        self.spotify         = spotify_client
        self.discord         = discord_client
        self.users           = user_lookup
        self.playlist_id     = playlist_id

        self.submissions_channel_id = os.environ.get("SUBMISSIONS_CHANNEL_ID", "")
        self.pending_channel_id     = os.environ.get("PENDING_CHANNEL_ID", "")
        self.trusted_role_id        = os.environ.get("TRUSTED_ROLE_ID", "")
        self.approver_discord_id    = os.environ.get("APPROVER_DISCORD_ID", "636545391973892098")

        # In-memory map of pending_message_id -> submission info
        # Persisted via github_storage between restarts
        self.pending = {}

    @property
    def _headers(self):
        return {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type":  "application/json",
        }

    # ── Discord REST helpers ──────────────────────────────────────────────────

    def _get(self, url, params=None):
        try:
            r = requests.get(url, headers=self._headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                retry_after = r.json().get("retry_after", 5)
                log.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(float(retry_after) + 0.5)
                return self._get(url, params)
            else:
                log.warning(f"GET {url} returned {r.status_code}")
                return None
        except requests.RequestException as e:
            log.warning(f"Network error: {e}")
            return None

    def _add_reaction(self, channel_id, message_id, emoji):
        """Add a reaction to a message (bot adds it so user can click it)."""
        encoded = requests.utils.quote(emoji, safe="")
        url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me"
        try:
            r = requests.put(url, headers=self._headers, timeout=10)
            if r.status_code not in (200, 204):
                log.warning(f"Could not add reaction {emoji}: {r.status_code}")
        except requests.RequestException as e:
            log.warning(f"Reaction network error: {e}")

    def _get_reactions(self, channel_id, message_id, emoji):
        """Get list of users who reacted with emoji on a message."""
        encoded = requests.utils.quote(emoji, safe="")
        url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}"
        result = self._get(url)
        return result if isinstance(result, list) else []

    def _get_recent_messages(self, channel_id, limit=50):
        """Fetch recent messages from a channel."""
        url = f"{DISCORD_API}/channels/{channel_id}/messages"
        result = self._get(url, params={"limit": limit})
        return result if isinstance(result, list) else []

    def _get_thread_messages(self, thread_id, limit=10):
        """Fetch messages from a thread (for rejection reason)."""
        url = f"{DISCORD_API}/channels/{thread_id}/messages"
        result = self._get(url, params={"limit": limit})
        return result if isinstance(result, list) else []

    def _post_message(self, channel_id, content):
        """Post a plain message to a channel."""
        url = f"{DISCORD_API}/channels/{channel_id}/messages"
        try:
            r = requests.post(url, json={"content": content}, headers=self._headers, timeout=10)
            if r.status_code in (200, 201):
                return r.json().get("id")
            else:
                log.warning(f"Post message failed: {r.status_code} {r.text[:200]}")
                return None
        except requests.RequestException as e:
            log.warning(f"Post message network error: {e}")
            return None

    def _create_thread_on_message(self, channel_id, message_id, thread_name):
        """Create a private thread on a message for rejection reason."""
        url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/threads"
        payload = {
            "name": thread_name,
            "auto_archive_duration": 1440,  # 24 hours
        }
        try:
            r = requests.post(url, json=payload, headers=self._headers, timeout=10)
            if r.status_code in (200, 201):
                return r.json().get("id")
            else:
                log.warning(f"Create thread failed: {r.status_code}")
                return None
        except requests.RequestException as e:
            log.warning(f"Create thread network error: {e}")
            return None

    def _is_trusted(self, member_roles):
        """Check if a list of role IDs includes the trusted role."""
        if not self.trusted_role_id:
            return False
        return self.trusted_role_id in member_roles

    def _get_member_roles(self, guild_id, user_id):
        """Fetch a member's roles from the guild."""
        if not guild_id:
            return []
        url = f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}"
        result = self._get(url)
        if result:
            return result.get("roles", [])
        return []

    # ── Spotify helpers ───────────────────────────────────────────────────────

    def _get_track_info(self, track_id):
        """Fetch track details from Spotify. Returns dict or None."""
        try:
            data = self.spotify._get(
                f"https://api.spotify.com/v1/tracks/{track_id}"
            )
            if not data:
                return None
            name   = data.get("name", "Unknown")
            artist = ", ".join(a["name"] for a in data.get("artists", []))
            url    = data.get("external_urls", {}).get("spotify", "")
            return {"id": track_id, "name": name, "artist": artist, "url": url}
        except Exception as e:
            log.warning(f"Could not fetch track info for {track_id}: {e}")
            return None

    def _artist_already_on_playlist(self, artist_name, current_tracks):
        """Check if an artist already has a song on the playlist."""
        artist_lower = artist_name.lower()
        for track in current_tracks.values():
            existing = track.get("artist", "").lower()
            # Check for overlap (handles 'Artist A, Artist B' cases)
            if artist_lower in existing or existing in artist_lower:
                return True, track.get("name", "Unknown")
        return False, None

    def _add_to_playlist(self, track_id):
        """Add a track to the Spotify playlist. Returns True on success."""
        url = f"https://api.spotify.com/v1/playlists/{self.playlist_id}/tracks"
        try:
            if not self.spotify.access_token:
                self.spotify.refresh_access_token()
            r = requests.post(
                url,
                json={"uris": [f"spotify:track:{track_id}"]},
                headers={
                    "Authorization": f"Bearer {self.spotify.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if r.status_code in (200, 201):
                log.info(f"Track {track_id} added to playlist.")
                return True
            elif r.status_code == 401:
                log.info("Access token expired during add. Refreshing...")
                self.spotify.access_token = None
                self.spotify.refresh_access_token()
                return self._add_to_playlist(track_id)  # retry once
            elif r.status_code == 403:
                log.error("403 adding to playlist — token missing playlist-modify-public scope.")
                return False
            else:
                log.error(f"Failed to add track: {r.status_code} {r.text[:200]}")
                return False
        except Exception as e:
            log.error(f"Exception adding track to playlist: {e}")
            return False

    # ── Main entry points (called from bot.py) ────────────────────────────────

    def check_new_submissions(self, guild_id, current_tracks):
        """
        Scan #song-submissions for new Spotify links and process them.
        Call this on every bot check cycle.
        """
        log.info(f"Checking submissions channel {self.submissions_channel_id}...")

        if not self.submissions_channel_id:
            log.warning("SUBMISSIONS_CHANNEL_ID not set — skipping submission check.")
            return

        messages = self._get_recent_messages(self.submissions_channel_id, limit=50)
        log.info(f"Fetched {len(messages) if messages else 0} messages from #song-submissions.")

        if not messages:
            return

        now = time.time()

        for msg in messages:
            msg_id        = msg.get("id", "")
            author        = msg.get("author", {})
            user_id       = author.get("id", "")
            content       = msg.get("content", "")
            timestamp     = msg.get("timestamp", "")

            # Skip bot messages
            if author.get("bot"):
                continue

            # Skip if we've already processed this message
            if self._already_processed(msg_id):
                log.info(f"Skipping already-processed message {msg_id}")
                continue

            # Only look at recent messages
            msg_age = self._message_age_seconds(timestamp)
            log.info(f"Message {msg_id} age: {int(msg_age)}s (limit: {SUBMISSION_LOOKBACK}s)")
            if msg_age > SUBMISSION_LOOKBACK:
                continue

            # Extract Spotify track link
            match = SPOTIFY_TRACK_RE.search(content)
            if not match:
                log.info(f"Message {msg_id} has no Spotify track link.")
                continue

            track_id = match.group(1)
            log.info(f"New submission from {user_id}: track {track_id}")

            # Fetch track info
            track = self._get_track_info(track_id)
            if not track:
                self._post_message(
                    self.submissions_channel_id,
                    f"<@{user_id}> Sorry, I couldn't look up that Spotify track. "
                    f"Please check the link and try again."
                )
                self._mark_processed(msg_id)
                continue

            # Check if already on playlist
            if track_id in current_tracks:
                self._post_message(
                    self.submissions_channel_id,
                    f"<@{user_id}> **{track['name']}** by {track['artist']} "
                    f"is already on the playlist!"
                )
                self._mark_processed(msg_id)
                continue

            # Check trusted role
            member_roles = self._get_member_roles(guild_id, user_id)
            is_trusted   = self._is_trusted(member_roles)

            # Check artist duplicate
            duplicate, existing_song = self._artist_already_on_playlist(
                track["artist"], current_tracks
            )

            submitter_name = self.users.get_name_by_discord(user_id) or f"<@{user_id}>"

            if is_trusted and not duplicate:
                # Auto-approve: add directly
                self._auto_approve(track, user_id, submitter_name, msg_id)
            else:
                # Route to #pending-approval
                self._send_to_pending(
                    track, user_id, submitter_name, msg_id,
                    is_trusted=is_trusted, duplicate=duplicate,
                    existing_song=existing_song
                )

            self._mark_processed(msg_id)

    def check_pending_reactions(self, current_tracks):
        """
        Poll #pending-approval messages for ✅/❌ reactions.
        Call this on every bot check cycle.
        """
        if not self.pending:
            return

        expired = []

        for pending_msg_id, info in list(self.pending.items()):
            age = time.time() - info.get("queued_at", 0)
            if age > REACTION_POLL_AGE:
                expired.append(pending_msg_id)
                continue

            # Check for ✅ approve reaction from the approver
            approve_users = self._get_reactions(
                self.pending_channel_id, pending_msg_id, "✅"
            )
            approver_reacted = any(
                str(u.get("id")) == str(self.approver_discord_id)
                for u in approve_users
                if not u.get("bot")
            )

            # Check for ❌ reject reaction from the approver
            reject_users = self._get_reactions(
                self.pending_channel_id, pending_msg_id, "❌"
            )
            rejector_reacted = any(
                str(u.get("id")) == str(self.approver_discord_id)
                for u in reject_users
                if not u.get("bot")
            )

            if approver_reacted:
                self._process_approval(pending_msg_id, info, current_tracks)
                expired.append(pending_msg_id)

            elif rejector_reacted:
                self._process_rejection(pending_msg_id, info)
                expired.append(pending_msg_id)

        for msg_id in expired:
            self.pending.pop(msg_id, None)

    # ── Internal handlers ─────────────────────────────────────────────────────

    def _auto_approve(self, track, user_id, submitter_name, original_msg_id):
        """Directly add a trusted player's song to the playlist."""
        log.info(f"Auto-approving {track['name']} for trusted player {submitter_name}")

        success = self._add_to_playlist(track["id"])
        if success:
            self._post_message(
                self.submissions_channel_id,
                f"✅ <@{user_id}> **{track['name']}** by {track['artist']} "
                f"has been added to the playlist!"
            )
            log.info(f"Auto-approved and added: {track['name']} -- {track['artist']}")
        else:
            self._post_message(
                self.submissions_channel_id,
                f"<@{user_id}> Your submission of **{track['name']}** was accepted "
                f"but failed to add to Spotify. The mod has been notified."
            )
            self.discord.post_to_alerts(
                f"⚠️ Auto-approval failed for Spotify add.\n"
                f"Track: {track['name']} by {track['artist']}\n"
                f"Submitted by: {submitter_name}\n"
                f"Track ID: {track['id']}"
            )

    def _send_to_pending(self, track, user_id, submitter_name, original_msg_id,
                         is_trusted=False, duplicate=False, existing_song=None):
        """Post submission to #pending-approval for mod review."""
        if not self.pending_channel_id:
            log.warning("PENDING_CHANNEL_ID not set — cannot route to pending.")
            return

        duplicate_warning = ""
        if duplicate:
            duplicate_warning = (
                f"\n⚠️ **ARTIST ALREADY ON PLAYLIST** — "
                f"{track['artist']} already has **{existing_song}** on the playlist."
            )

        trusted_note = ""
        if is_trusted:
            trusted_note = "\n🔵 *Trusted player — flagged only due to duplicate artist*"

        content = (
            f"🎵 **New Submission**\n"
            f"Track: **{track['name']}**\n"
            f"Artist: {track['artist']}\n"
            f"Submitted by: {submitter_name}\n"
            f"Link: {track['url']}"
            f"{duplicate_warning}"
            f"{trusted_note}\n\n"
            f"React ✅ to approve or ❌ to reject.\n"
            f"If rejecting, reply in this channel with the reason — "
            f"the bot will forward it to the submitter."
        )

        msg_id = self._post_message(self.pending_channel_id, content)
        if not msg_id:
            log.error("Failed to post to #pending-approval.")
            return

        # Bot adds the reactions so mod can just click
        time.sleep(0.5)
        self._add_reaction(self.pending_channel_id, msg_id, "✅")
        time.sleep(0.5)
        self._add_reaction(self.pending_channel_id, msg_id, "❌")

        # Store in pending map
        self.pending[msg_id] = {
            "track":           track,
            "user_id":         user_id,
            "submitter_name":  submitter_name,
            "original_msg_id": original_msg_id,
            "queued_at":       time.time(),
        }

        log.info(
            f"Submission from {submitter_name} queued for approval: "
            f"{track['name']} -- {track['artist']}"
        )

    def _process_approval(self, pending_msg_id, info, current_tracks):
        """Handle mod ✅ reaction — add song to playlist."""
        track          = info["track"]
        user_id        = info["user_id"]
        submitter_name = info["submitter_name"]

        log.info(f"Approving {track['name']} by {track['artist']}")

        # Double-check it hasn't been added in the meantime
        if track["id"] in current_tracks:
            self._post_message(
                self.submissions_channel_id,
                f"<@{user_id}> **{track['name']}** by {track['artist']} "
                f"was approved but is already on the playlist."
            )
            return

        success = self._add_to_playlist(track["id"])
        if success:
            self._post_message(
                self.submissions_channel_id,
                f"✅ <@{user_id}> Your submission **{track['name']}** by "
                f"{track['artist']} has been approved and added to the playlist!"
            )
            log.info(f"Approved and added: {track['name']} -- {track['artist']}")
        else:
            self._post_message(
                self.submissions_channel_id,
                f"<@{user_id}> Your submission **{track['name']}** was approved "
                f"but failed to add to Spotify. The mod has been notified."
            )
            self.discord.post_to_alerts(
                f"⚠️ Approval succeeded but Spotify add failed.\n"
                f"Track: {track['name']} by {track['artist']}\n"
                f"Submitted by: {submitter_name}\n"
                f"Track ID: {track['id']}\n"
                f"Please add manually."
            )

    def _process_rejection(self, pending_msg_id, info):
        """
        Handle mod ❌ reaction.
        Look for a reply from the mod in #pending-approval as the reason,
        then post it back to the submitter.
        """
        track          = info["track"]
        user_id        = info["user_id"]
        submitter_name = info["submitter_name"]
        queued_at      = info.get("queued_at", 0)

        log.info(f"Rejecting {track['name']} by {track['artist']}")

        # Look for a reply message from the approver posted after the pending msg
        reason = self._find_rejection_reason(pending_msg_id, queued_at)

        if reason:
            self._post_message(
                self.submissions_channel_id,
                f"<@{user_id}> Your submission **{track['name']}** by "
                f"{track['artist']} was not approved.\n"
                f"Reason: {reason}"
            )
        else:
            self._post_message(
                self.submissions_channel_id,
                f"<@{user_id}> Your submission **{track['name']}** by "
                f"{track['artist']} was not approved at this time."
            )

        log.info(f"Rejection posted to submitter {submitter_name}.")

    def _find_rejection_reason(self, pending_msg_id, queued_at):
        """
        Look for a message from the approver in #pending-approval
        that was posted after the pending message (i.e. the rejection reason).
        Returns the text or None.
        """
        messages = self._get_recent_messages(self.pending_channel_id, limit=20)
        for msg in messages:
            author_id = msg.get("author", {}).get("id", "")
            if str(author_id) != str(self.approver_discord_id):
                continue
            if msg.get("author", {}).get("bot"):
                continue
            # Must be newer than when we queued the submission
            msg_age = self._message_age_seconds(msg.get("timestamp", ""))
            msg_time = time.time() - msg_age
            if msg_time > queued_at:
                return msg.get("content", "").strip()
        return None

    # ── State persistence helpers ─────────────────────────────────────────────

    def load_pending(self, data):
        """Load pending submissions from persisted data (dict)."""
        if isinstance(data, dict):
            self.pending = data
            log.info(f"Loaded {len(self.pending)} pending submissions.")

    def dump_pending(self):
        """Return pending dict for persistence."""
        return self.pending

    # ── Utility ───────────────────────────────────────────────────────────────

    def _already_processed(self, msg_id):
        """Check if we've already handled this submission message."""
        # A message is processed if it's already in pending or was acted on
        return msg_id in self.pending or msg_id in _processed_cache

    def _mark_processed(self, msg_id):
        _processed_cache.add(msg_id)

    def _message_age_seconds(self, timestamp_str):
        """Convert ISO timestamp to age in seconds."""
        if not timestamp_str:
            return 999999
        try:
            from datetime import datetime, timezone
            # Discord timestamps can have +00:00 or Z
            ts = timestamp_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            return (now - dt).total_seconds()
        except Exception:
            return 999999


# Module-level set to track processed message IDs (avoids double-processing)
_processed_cache = set()
