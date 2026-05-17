"""
scoring.py

Tracks and calculates Drop Cred points for all users.
Scans Discord channels for activity and attributes points.

Point system:
  8  - Adding a song to the playlist (via Spotify)
  8  - Challenging a song (posting in #challenges)
  5  - Your song gets challenged
  4  - Creating a new post anywhere
  3  - Someone ❤️ your post
  2  - Commenting anywhere
  1  - Reacting ❤️ to someone's post
  5  - Bonus: your post reaches 5 ❤️ reactions
  10 - Bonus: your post reaches 10 ❤️ reactions

Badges:
  🎧 New Dropper  0+
  📀 Crate Digger 50+
  🔥 Drop Dealer  200+
  👑 Canon Builder 400+
  🌀 Definitive   500+
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import requests

log = logging.getLogger("scoring")

SCORES_FILE      = "drop_cred_scores.json"
SCANNED_FILE     = "drop_cred_scanned.json"  # tracks what we've already scored
HEART_EMOJI      = "❤️"

POINTS = {
    "song_added":        8,
    "challenge_posted":  8,
    "song_challenged":   5,
    "new_post":          4,
    "heart_received":    3,
    "comment":           2,
    "heart_given":       1,
    "milestone_5":       5,
    "milestone_10":     10,
}

BADGES = [
    (500, "🌀 Definitive"),
    (400, "👑 Canon Builder"),
    (200, "🔥 Drop Dealer"),
    (50,  "📀 Crate Digger"),
    (0,   "🎧 New Dropper"),
]

def get_badge(points):
    for threshold, name in BADGES:
        if points >= threshold:
            return name
    return "🎧 New Dropper"


# ── Score persistence ──────────────────────────────────────────────────────────

def load_scores():
    """Load scores from disk. Returns dict of display_name -> score data."""
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Could not load scores: {e}")
    return {}

def save_scores(scores):
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2)

def load_scanned():
    """Load record of what we've already scanned/scored."""
    if os.path.exists(SCANNED_FILE):
        try:
            with open(SCANNED_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "scored_messages":   [],   # message IDs already scored for comments
        "scored_reactions":  {},   # message_id -> list of user_ids already scored
        "scored_milestones": {},   # message_id -> list of milestones already awarded
        "scored_songs":      [],   # track IDs already scored for song_added
        "scored_challenges": [],   # message IDs already scored for challenge_posted
        "last_scan":         None,
    }

def save_scanned(scanned):
    with open(SCANNED_FILE, "w") as f:
        json.dump(scanned, f, indent=2)


# ── Score manipulation ────────────────────────────────────────────────────────

def ensure_user(scores, display_name):
    """Ensure a user exists in the scores dict."""
    if display_name not in scores:
        scores[display_name] = {
            "total":        0,
            "weekly":       0,
            "week_start":   _current_week_start(),
            "breakdown":    {},
            "badge":        "🎧 New Dropper",
        }
    return scores[display_name]

def _current_week_start():
    """Get the start of the current week (Monday) as ISO string."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

def add_points(scores, display_name, action, amount=None):
    """Add points to a user's score. Returns (new_total, badge_changed, new_badge)."""
    pts = amount if amount is not None else POINTS.get(action, 0)
    if pts == 0:
        return None, False, None

    user = ensure_user(scores, display_name)
    old_badge = user["badge"]

    user["total"]  += pts
    user["weekly"] += pts
    user["breakdown"][action] = user["breakdown"].get(action, 0) + pts

    new_badge = get_badge(user["total"])
    user["badge"] = new_badge

    badge_changed = new_badge != old_badge
    log.info(f"  +{pts} pts ({action}) -> {display_name} (total: {user['total']})")
    return user["total"], badge_changed, new_badge if badge_changed else None

def reset_weekly_scores(scores):
    """Reset all weekly scores (called every Sunday)."""
    for user in scores.values():
        user["weekly"]     = 0
        user["week_start"] = _current_week_start()
    log.info("Weekly scores reset.")


# ── Discord scanning ──────────────────────────────────────────────────────────

class ScoreScanner:
    def __init__(self, bot_token, user_lookup, excluded_channel_ids=None):
        self.token             = bot_token
        self.users             = user_lookup
        self.excluded_channels = set(excluded_channel_ids or [])
        self.headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type":  "application/json",
        }

    def _get(self, url, retries=3):
        for attempt in range(retries):
            try:
                r = requests.get(url, headers=self.headers, timeout=15)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 429:
                    wait = float(r.json().get("retry_after", 5))
                    log.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait + 0.5)
                    continue
                elif r.status_code == 403:
                    log.warning(f"No access to {url}")
                    return None
                elif r.status_code == 404:
                    return None
                else:
                    log.warning(f"GET {url} returned {r.status_code}")
                    time.sleep(2 ** attempt)
            except requests.RequestException as e:
                log.warning(f"Network error: {e}")
                time.sleep(2 ** attempt)
        return None

    def get_guild_channels(self, guild_id):
        """Get all channels in the server."""
        data = self._get(f"https://discord.com/api/v10/guilds/{guild_id}/channels")
        if not data:
            return []
        return [
            ch for ch in data
            if str(ch.get("id")) not in self.excluded_channels
        ]

    def get_channel_messages(self, channel_id, limit=100, before=None):
        """Get messages from a channel."""
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
        if before:
            url += f"&before={before}"
        return self._get(url) or []

    def get_all_messages(self, channel_id, max_messages=1000):
        """Get all messages from a channel with pagination."""
        all_messages = []
        before = None
        while len(all_messages) < max_messages:
            batch = self.get_channel_messages(channel_id, limit=100, before=before)
            if not batch:
                break
            all_messages.extend(batch)
            if len(batch) < 100:
                break
            before = batch[-1]["id"]
            time.sleep(0.5)
        return all_messages

    def get_all_reactors(self, channel_id, message_id, message):
        """
        Get reaction data from a message efficiently.
        
        Uses reaction counts already in the message data to avoid
        excessive API calls. Only fetches reactor IDs for the heart
        emoji (needed for attribution of heart_received points).
        
        Returns:
          all_reactor_ids: set of Discord IDs who reacted with ANY emoji
                           (estimated from reaction counts — used for heart_given)
          heart_count: number of heart reactions (for milestones)
          heart_reactor_ids: set of Discord IDs who reacted with ❤️
                             (for awarding heart_received points)
        """
        reactions = message.get("reactions", [])
        if not reactions:
            return set(), 0, set()

        heart_count       = 0
        heart_reactor_ids = set()
        total_reaction_count = 0

        for reaction in reactions:
            emoji      = reaction.get("emoji", {})
            emoji_name = emoji.get("name", "")
            count      = reaction.get("count", 0)
            total_reaction_count += count

            # Track heart reactions — fetch who reacted for attribution
            if emoji_name in ("❤️", "❤"):
                heart_count = count
                if count > 0:
                    import urllib.parse
                    encoded = urllib.parse.quote("❤️")
                    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded}?limit=100"
                    data = self._get(url)
                    if data:
                        heart_reactor_ids = {
                            str(u["id"]) for u in data if not u.get("bot")
                        }

        # For non-heart reactions, we know someone reacted but not who.
        # We award heart_given points only for heart reactions where we
        # know the reactor. This keeps API calls manageable.
        return heart_reactor_ids, heart_count, heart_reactor_ids

    def get_forum_threads(self, channel_id):
        """Get all active threads in a forum channel."""
        threads = []
        url = f"https://discord.com/api/v10/channels/{channel_id}/threads/search?limit=25"
        while url:
            data = self._get(url)
            if not data:
                break
            batch = data.get("threads", [])
            threads.extend(batch)
            if data.get("has_more") and batch:
                last_id = batch[-1]["id"]
                url = f"https://discord.com/api/v10/channels/{channel_id}/threads/search?limit=25&before={last_id}"
            else:
                url = None
            time.sleep(0.5)

        # Also get archived threads
        url = f"https://discord.com/api/v10/channels/{channel_id}/threads/archived/public?limit=25"
        while url:
            data = self._get(url)
            if not data:
                break
            batch = data.get("threads", [])
            threads.extend(batch)
            if data.get("has_more") and batch:
                last_id = batch[-1]["id"]
                url = f"https://discord.com/api/v10/channels/{channel_id}/threads/archived/public?limit=25&before={last_id}"
            else:
                url = None
            time.sleep(0.5)

        return threads

    def score_song_post(self, scores, scanned, message, playlist_channel_id):
        """
        Score a bot post in #the-playlist for 'song_added'.
        Parses 'Added by:' from the bot's own post format.
        """
        msg_id      = message["id"]
        content     = message.get("content", "")
        author_id   = str(message.get("author", {}).get("id", ""))

        # Only process bot posts
        if not self.users.is_bot(author_id):
            return [], []

        # Already scored this song post?
        if msg_id in scanned["scored_songs"]:
            return [], []

        # Parse "Added by:" from content
        added_by_name = None
        for line in content.split("\n"):
            if line.startswith("Added by:"):
                name = line.replace("Added by:", "").strip()
                added_by_name = name
                break

        if not added_by_name:
            return [], []

        # Try to resolve the name to a known user.
        # Checks: exact display name match, alias match, Spotify ID match.
        display_name = None
        for user in self.users.get_all_users():
            # Exact display name match
            if user["display_name"] == added_by_name:
                display_name = user["display_name"]
                break
            # Alias match (e.g. "Marianne Hartman Tichenor" -> "MHT")
            if added_by_name in user.get("aliases", []):
                display_name = user["display_name"]
                log.info(f"Resolved alias '{added_by_name}' -> '{display_name}'")
                break
            # Spotify ID match (for posts made before display name was known)
            if user.get("spotify_id") == added_by_name:
                display_name = user["display_name"]
                break

        if not display_name:
            log.warning(f"Could not resolve '{added_by_name}' to a known user for song scoring.")
            return [], []

        points_events = []
        badge_events  = []

        total, badge_changed, new_badge = add_points(scores, display_name, "song_added")
        points_events.append((display_name, "song_added", POINTS["song_added"]))
        if badge_changed:
            badge_events.append((display_name, new_badge))

        scanned["scored_songs"].append(msg_id)
        return points_events, badge_events

    def score_message(self, scores, scanned, message, channel_id, channel_type="text"):
        """
        Score a single message for comments and new posts.
        channel_type: 'text', 'forum_thread', 'challenges'
        """
        msg_id    = message["id"]
        author    = message.get("author", {})
        author_id = str(author.get("id", ""))

        # Skip bots
        if self.users.is_bot(author_id) or author.get("bot"):
            return [], [], []

        display_name = self.users.get_name_by_discord(author_id)
        if not display_name:
            return [], [], [author_id]  # unknown discord user

        points_events = []
        badge_events  = []

        # Score as comment if not already scored
        if msg_id not in scanned["scored_messages"]:
            # Is this a challenge post?
            if channel_type == "challenges":
                total, bc, nb = add_points(scores, display_name, "challenge_posted")
                points_events.append((display_name, "challenge_posted", POINTS["challenge_posted"]))
                if bc:
                    badge_events.append((display_name, nb))
            else:
                total, bc, nb = add_points(scores, display_name, "comment")
                points_events.append((display_name, "comment", POINTS["comment"]))
                if bc:
                    badge_events.append((display_name, nb))
            scanned["scored_messages"].append(msg_id)

        # Score reactions on this message
        reaction_scorers = scanned["scored_reactions"].get(msg_id, [])
        heart_reactor_ids, heart_count, _ = self.get_all_reactors(channel_id, msg_id, message)

        for reactor_id in heart_reactor_ids:
            if reactor_id in reaction_scorers:
                continue
            if self.users.is_bot(reactor_id):
                continue

            reactor_name = self.users.get_name_by_discord(reactor_id)
            if reactor_name:
                # Reactor gets 1 point for giving a heart
                total, bc, nb = add_points(scores, reactor_name, "heart_given")
                points_events.append((reactor_name, "heart_given", POINTS["heart_given"]))
                if bc:
                    badge_events.append((reactor_name, nb))

            # Post author gets 3 points for receiving a heart
            total, bc, nb = add_points(scores, display_name, "heart_received")
            points_events.append((display_name, "heart_received", POINTS["heart_received"]))
            if bc:
                badge_events.append((display_name, nb))

            reaction_scorers.append(reactor_id)

        scanned["scored_reactions"][msg_id] = reaction_scorers

        # Score milestones
        scored_milestones = scanned["scored_milestones"].get(msg_id, [])
        if heart_count >= 10 and "milestone_10" not in scored_milestones:
            total, bc, nb = add_points(scores, display_name, "milestone_10")
            points_events.append((display_name, "milestone_10", POINTS["milestone_10"]))
            if bc:
                badge_events.append((display_name, nb))
            scored_milestones.append("milestone_10")
        elif heart_count >= 5 and "milestone_5" not in scored_milestones:
            total, bc, nb = add_points(scores, display_name, "milestone_5")
            points_events.append((display_name, "milestone_5", POINTS["milestone_5"]))
            if bc:
                badge_events.append((display_name, nb))
            scored_milestones.append("milestone_5")

        scanned["scored_milestones"][msg_id] = scored_milestones

        return points_events, badge_events, []

    def scan_all(self, guild_id, forum_channel_id, challenges_channel_id,
                 scores, scanned):
        """
        Full scan of all server activity.
        Returns (all_points_events, all_badge_events, unknown_discord_ids).
        """
        all_points  = []
        all_badges  = []
        unknown_ids = set()

        channels = self.get_guild_channels(guild_id)
        log.info(f"Scanning {len(channels)} channels for activity...")

        for ch in channels:
            ch_id   = str(ch["id"])
            ch_name = ch.get("name", ch_id)
            ch_type = ch.get("type", 0)

            # Type 15 = forum channel
            if ch_type == 15:
                # Scan forum threads
                threads = self.get_forum_threads(ch_id)
                log.info(f"  #{ch_name}: {len(threads)} threads")
                for thread in threads:
                    thread_id = str(thread["id"])
                    # Score the opening post (new_post)
                    thread_msgs = self.get_all_messages(thread_id)
                    for i, msg in enumerate(thread_msgs):
                        if i == 0:
                            # Opening post
                            if ch_id == str(forum_channel_id):
                                # Score song added from bot post
                                pe, be = self.score_song_post(scores, scanned, msg, ch_id)
                                all_points.extend(pe)
                                all_badges.extend(be)
                            else:
                                pe, be, unk = self.score_message(scores, scanned, msg, thread_id, "forum_thread")
                                all_points.extend(pe)
                                all_badges.extend(be)
                                unknown_ids.update(unk)
                        else:
                            # Reply/comment
                            pe, be, unk = self.score_message(scores, scanned, msg, thread_id, "forum_thread")
                            all_points.extend(pe)
                            all_badges.extend(be)
                            unknown_ids.update(unk)
                        time.sleep(0.1)

            # Type 0 = text channel
            elif ch_type == 0:
                is_challenges = ch_id == str(challenges_channel_id)
                messages = self.get_all_messages(ch_id)
                log.info(f"  #{ch_name}: {len(messages)} messages")
                for msg in messages:
                    ch_type_label = "challenges" if is_challenges else "text"
                    pe, be, unk = self.score_message(scores, scanned, msg, ch_id, ch_type_label)
                    all_points.extend(pe)
                    all_badges.extend(be)
                    unknown_ids.update(unk)
                    time.sleep(0.1)

        # Remove known users from unknown set
        known_discord_ids = {
            str(u["discord_id"])
            for u in self.users.get_all_users()
            if u.get("discord_id")
        }
        unknown_ids -= known_discord_ids

        log.info(f"Scan complete. {len(all_points)} point events, {len(all_badges)} badge events, {len(unknown_ids)} unknown Discord users.")
        return all_points, all_badges, list(unknown_ids)
