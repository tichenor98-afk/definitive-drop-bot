""" 
bot.py
Main bot loop. Coordinates Spotify monitoring, Discord posting,
activity scoring, leaderboard management, and song submission workflow.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone

from spotify_client import SpotifyClient, SpotifyError, SpotifyTokenExpiredError
from discord_client import DiscordClient, DiscordError
from state_manager  import (
    load_state, save_state, load_backup_state,
    initialize_state, validate_state, StateError,
)
from user_lookup  import UserLookup
from scoring      import (
    load_scores, save_scores, load_scanned, save_scanned,
    add_points, reset_weekly_scores, ScoreScanner, POINTS,
)
from leaderboard       import update_pinned_leaderboard, post_weekly_announcement
from github_storage    import setup_storage
from submission_manager import SubmissionManager

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bot")

# ── Config ────────────────────────────────────────────────────────────────────
def require_env(key):
    val = os.environ.get(key)
    if not val:
        print(f"FATAL: Required environment variable {key} is not set.")
        sys.exit(1)
    return val

SPOTIFY_CLIENT_ID     = require_env("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = require_env("SPOTIFY_CLIENT_SECRET")
SPOTIFY_PLAYLIST_ID   = require_env("SPOTIFY_PLAYLIST_ID")
DISCORD_BOT_TOKEN     = require_env("DISCORD_BOT_TOKEN")
FORUM_CHANNEL_ID      = require_env("FORUM_CHANNEL_ID")
UPDATES_CHANNEL_ID    = require_env("UPDATES_CHANNEL_ID")
ALERTS_CHANNEL_ID     = require_env("ALERTS_CHANNEL_ID")
USERS_SHEET_CSV_URL   = require_env("USERS_SHEET_CSV_URL")
INTRODUCE_CHANNEL_ID  = os.environ.get("INTRODUCE_CHANNEL_ID",  "1505574947861303416")
DROP_CRED_CHANNEL_ID  = os.environ.get("DROP_CRED_CHANNEL_ID",  "1505592556908449967")
CHALLENGES_CHANNEL_ID = os.environ.get("CHALLENGES_CHANNEL_ID", "")
GUILD_ID              = os.environ.get("GUILD_ID", "")

# Submission system (new)
SUBMISSIONS_CHANNEL_ID = os.environ.get("SUBMISSIONS_CHANNEL_ID", "")
PENDING_CHANNEL_ID     = os.environ.get("PENDING_CHANNEL_ID", "")
TRUSTED_ROLE_ID        = os.environ.get("TRUSTED_ROLE_ID", "")
APPROVER_DISCORD_ID    = os.environ.get("APPROVER_DISCORD_ID", "636545391973892098")

EXCLUDED_CHANNEL_IDS  = {ALERTS_CHANNEL_ID}

CHECK_INTERVAL        = int(os.environ.get("CHECK_INTERVAL", "600"))
SCORE_SCAN_INTERVAL   = int(os.environ.get("SCORE_SCAN_INTERVAL", "1800"))
SCAN_REQUEST_DELAY    = float(os.environ.get("SCAN_REQUEST_DELAY", "2.0"))
GITHUB_REPO           = os.environ.get("GITHUB_REPO", "tichenor98-afk/definitive-drop-bot")
LEADERBOARD_INTERVAL  = int(os.environ.get("LEADERBOARD_INTERVAL", "86400"))
HEARTBEAT_INTERVAL    = 86400
TOKEN_FILE            = "spotify_token.json"

LEGACY_TRACK_IDS = set(["7lQy8vI73IL4Wft8I4eA5Z", "0lJK5ZmN9K4IaEi6QHj5W8", "2gG7E5OZi5D5QLRIctv63z", "6uWV09syluMJlYbAHgLRhn", "1nYg1Ac4xsGBkmTvhXDzG2", "5A9mGMMsmySIZmBH6icc4B", "01Oi7A4u4knAEPqylXM9s8", "6H3kDe7CGoWYBabAeVWGiD", "35q1B8x7zRsITx6SxcWK67", "5CIe9u7lex3fxPmwWqrjo3", "7rBMZvgeWnOTHWUh3Pvw51", "0wZurfElW3yOHscb38vBL8", "0m1DJ5Jkv3kdnGrcZsJFmC", "5pK4elvBpzeAk8amFG3NVN", "0whFZ2qMsiUMkQOxsfRy5p", "78sUOio7Q63zyraK2auLla", "0BqQWfhMrkpRAUCbdfdHUC", "4dT3qLUU6fFUmomLzk2cUA", "5ynO8cYFjDwELIZfFHHeYe", "2fUesvrGtDQ37bUz30nMak", "1rmtygBvOF8Wb1OwVMAyaE", "0P2vAvvWni2tNXOdbH3JFk", "0xeBC6N81ZBYDtxuBFGSuO", "750wm5pwuAQfnSLX8mxa5f", "6QewNVIDKdSl8Y3ycuHIei", "3aKhLm5mONfAtS1NZXG8f4", "2lp0PO2D90zcFWy8toVqgn", "0hSUqAj87s0gHUS8U4TRIF", "1dfHpGeaXunLRNvzSZOZtc", "4E5xVW505akJX0wcKj8Mpd", "60QLLec3yKDwloXCyummPy", "4EchqUKQ3qAQuRNKmeIpnf", "43G3McVkRa8V7oGQzfQuRr", "3lSrLqwpS23lMqhtDierCq", "1h2xVEoJORqrg71HocgqXd", "2SIVPuWP84mPNhF0Ns9nWC", "6zsk6uF3MxfIeHPlubKBvR", "31er9IGsfFbwqy1pH4aiTP", "2NVpYQqdraEcQwqT7GhUkh", "0bJKesHl9raebAYBpQp3wv", "0L7zm6afBEtrNKo6C6Gj08", "6QyBIZEvs11K9lKjyLYtv6", "5CeL9C3bsoe4yzYS1Qz8cw", "07p7PALHp6ZcD5tmlbO94N", "41eFwwTvEhuBgE4SAXxRGd", "69MwNXryg6NT1lV7buN7U7", "0wZYfxL16dtfTvxFpWTB7L", "2IKd8ozOHYuVqrYJ0tqghP", "50fGkq9l9Zsn1x7C8GKIYr", "0uppYCG86ajpV2hSR3dJJ0", "6dmiV9JGjv4vGgLwEZTaOI", "4v2rkl1mC3zVAz0nXMx9r4", "2TVutF2Xy9R6PLVQ5jEEUs", "4KxhIoBjdvaIGA5U6a1c3o", "0LtsuNRz3IMRrHCYO9fKRk", "4jQDaI7FRGaDB0llURpnNf", "0z8oPUM05RZBJ1A1dXPsSs", "3CIOopLwvyMvXk97ZEksKO", "4xVXe1VS5zlQyECVk6GRrL", "54bm2e3tk8cliUz3VSdCPZ", "154gL4Xb5AsreMkcDlVFYS", "1672RT45nXNUb28fzzPxn8", "1a19jsjG2DvbN1fVJonKUU", "3fkPMWQ6cBNBLuFcPyMS8s", "4E0P1xs3JNmsNr5c5nFTZJ", "6CxQsBfTmhx0RsoJoV8hH7", "3agtg0x11wPvLIWkYR39nZ", "5UWwZ5lm5PKu6eKsHAGxOk", "6J5kc12BW5HuP3d7C3vvx8", "27BgDmciSjoxTG0almHTpZ", "0N3W5peJUQtI4eyR6GJT5O", "4fjWStUaP7aXdT0d3YxvPo", "2gdtLnVGGg80Kj9GiqP0vH", "06h9kk12VjJ2bqcBc6IScR", "5sFDReWLrZHLFZFjHsjUTS", "5fKZJHzJ9d3MADArbm9muW", "0bt3YJTupDqdTKpnFFgs7f", "6cr6UDpkjEaMQ80OjWqEBQ", "7k0UY4Kabh7SUHXowyfKj7", "2amzrvbxYiq8AxGntIiw5V", "20KSB3DRekMDCb31rY0ATd", "3gjHnylel3PTRpjS44ocqr", "7DD7eSuYSC5xk2ArU62esN", "5b1jZ9geGD4boxz24XgGPp", "033N3Mf87ODmORg6YO61cm", "7fcfNW0XxTWlwVlftzfDOR", "2id8E4WvczfKHB4LHI7Np3", "7qj6lBOB1QTgBmKedXuIbs", "2PpNgmrS9mAyrkRAwn6YPq", "1CM1wOqD2AIjt2MWd31LV2", "2V4Bc2I962j7acQj1N0PiQ", "2QSUyofqpGDCo026OPiTBQ", "53DfWyh0C0rJUGpsmtdRc1", "3YuaBvuZqcwN3CEAyyoaei", "5EicljVZKVOo2LZHREtWmQ", "0xaNdYwK8ZF3cHSjraQGC0", "3QZ7uX97s82HFYSmQUAN1D", "4pzcMiIkEv8cOe5vD7xfGq", "2VGf3YQ6Zfzb6YyDatYAcY", "10V8XpuyMoEcSMfM79WDET", "0hDQV9X1Da5JrwhK8gu86p", "2854fjg3reX87rDKe6Bk73", "4C7Ss9bTPOWJMh3rarF1mN", "0ObrXLrfrqJUNc8RfmIBHP", "0Dw9z44gXhplDh5HCWZIxP", "2Bux4j9el8GFOrvAE8dMA3", "4VwPsMcRt1HPVKIdcwY9Uj", "2AdRSHeYmDGMrgIfiS2w7K", "5Cr3dgYZKJrUTJjy2bEaYa", "006yvCdaWUS79qp2Ip3Hdl", "26Kw6zBo3Uy98q5LTlFfVJ", "1H4idkmruFoJBg1DvUv2tY", "54bO2CHOgGN44oWmAqib0I"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_date(iso):
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%B %d, %Y")
    except Exception:
        return iso

def now_str():
    return datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

def now_date():
    return datetime.now(timezone.utc).strftime("%B %d, %Y")

# ── Song handlers ─────────────────────────────────────────────────────────────

def handle_added_song(track_id, track, discord, users, state, scores, scanned):
    name      = track["name"]
    artist    = track["artist"]
    url       = track["url"]
    added_by  = users.get_name(track.get("added_by", ""))
    added_at  = fmt_date(track.get("added_at", "")) or now_date()

    log.info(f"New song: {name} -- {artist} (added by {added_by})")

    # Alert and introduce unknown Spotify user
    if track.get("added_by") and users.is_unknown(track.get("added_by", "")):
        spotify_id = track["added_by"]
        discord.post_to_alerts(
            f"⚠️ Unknown Spotify user `{spotify_id}` added a song.\n"
            f"Song: {name} by {artist}\n"
            f"Add them to user_lookup.py so their name shows correctly."
        )
        discord.post_message(
            INTRODUCE_CHANNEL_ID,
            f"🎵 **{name}** by **{artist}** just landed on the playlist — nice pick!\n"
            f"But who ARE you?! Spotify says `{spotify_id}` but that's not a name 😄\n"
            f"Drop your name below so we can make it official!"
        )

    # Create forum post in #the-playlist
    post_content = (
        f"🎵 **{name}**\n"
        f"Artist: {artist}\n"
        f"Added by: {added_by}\n"
        f"Added: {added_at}\n"
        f"{url}"
    )
    try:
        thread_id = discord.create_forum_post(f"{name} — {artist}", post_content)
    except DiscordError as e:
        log.error(f"Failed to create forum post for {name}: {e}")
        discord.post_to_alerts(
            f"⚠️ Failed to create Discord post for: {name} by {artist}\n"
            f"Error: {e}\n"
            f"Please add this song manually to #the-playlist."
        )
        thread_id = None

    time.sleep(1)

    # Log in #playlist-updates
    try:
        discord.post_to_updates(
            f"✅ **Song Added**\n"
            f"Track: {name}\n"
            f"Artist: {artist}\n"
            f"Added by: {added_by}\n"
            f"Added: {added_at}"
        )
    except DiscordError as e:
        log.error(f"Failed to post to #playlist-updates: {e}")

    # Award points
    if added_by and added_by != track.get("added_by", ""):
        total, badge_changed, new_badge = add_points(scores, added_by, "song_added")
        if badge_changed:
            announce_badge(discord, added_by, new_badge)

    state[track_id] = {
        "thread_id": thread_id,
        "name":      name,
        "artist":    artist,
    }
    time.sleep(1)


def handle_removed_song(track_id, song_state, discord):
    name      = song_state.get("name", track_id)
    artist    = song_state.get("artist", "")
    thread_id = song_state.get("thread_id")
    removed_date = now_date()

    log.info(f"Removed: {name} -- {artist}")

    if thread_id:
        commented = discord.comment_on_post(thread_id, f"Removed {removed_date}")
        if not commented:
            discord.post_to_alerts(
                f"⚠️ Could not comment on Discord post for removed song: {name} by {artist}"
            )
    else:
        log.info(f"No thread ID for {name} — legacy song, skipping comment.")

    time.sleep(1)

    try:
        discord.post_to_updates(
            f"❌ **Song Removed**\n"
            f"Track: {name}\n"
            f"Artist: {artist}\n"
            f"Removed: {removed_date}"
        )
    except DiscordError as e:
        log.error(f"Failed to post removal to #playlist-updates: {e}")

    time.sleep(1)


def announce_badge(discord, display_name, new_badge):
    try:
        discord.post_message(
            DROP_CRED_CHANNEL_ID,
            f"🎉 **{display_name}** just leveled up to **{new_badge}** status! Keep it up! 🎵"
        )
    except Exception as e:
        log.warning(f"Could not post badge announcement: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print("[bot] main() started — new code running", flush=True)
    log.info("=" * 60)
    log.info("Definitive Drop Playlist Bot starting...")
    log.info("=" * 60)

    spotify = SpotifyClient(
        client_id     = SPOTIFY_CLIENT_ID,
        client_secret = SPOTIFY_CLIENT_SECRET,
        playlist_id   = SPOTIFY_PLAYLIST_ID,
        token_file    = TOKEN_FILE,
    )
    discord = DiscordClient(
        bot_token          = DISCORD_BOT_TOKEN,
        forum_channel_id   = FORUM_CHANNEL_ID,
        updates_channel_id = UPDATES_CHANNEL_ID,
        alerts_channel_id  = ALERTS_CHANNEL_ID,
    )
    users   = UserLookup(None)
    scanner = ScoreScanner(
        bot_token            = DISCORD_BOT_TOKEN,
        user_lookup          = users,
        excluded_channel_ids = EXCLUDED_CHANNEL_IDS,
        request_delay        = SCAN_REQUEST_DELAY,
    )
    submissions = SubmissionManager(
        bot_token      = DISCORD_BOT_TOKEN,
        spotify_client = spotify,
        discord_client = discord,
        user_lookup    = users,
        playlist_id    = SPOTIFY_PLAYLIST_ID,
    )

    # Startup checks
    try:
        discord.test_connection()
    except DiscordError as e:
        log.error(f"Discord connection failed: {e}")
        sys.exit(1)

    try:
        spotify.refresh_access_token()
    except SpotifyTokenExpiredError as e:
        # Refresh token has expired — alert and exit cleanly
        log.error(f"Spotify refresh token expired: {e}")
        discord.post_to_alerts(
            f"🔴 **ACTION REQUIRED — Spotify token expired**\n"
            f"{e}\n\n"
            f"Steps to fix:\n"
            f"1. On your computer, run: `python get_spotify_token.py`\n"
            f"2. Upload the new `spotify_token.json` to GitHub\n"
            f"3. Railway will redeploy automatically\n\n"
            f"The bot will not restart until the token is replaced."
        )
        sys.exit(1)
    except SpotifyError as e:
        log.error(f"Spotify token refresh failed: {e}")
        discord.post_to_alerts(f"⚠️ Bot failed to start: {e}")
        sys.exit(1)

    # Load state and scores
    try:
        state = load_state()
    except StateError as e:
        log.warning(f"State problem: {e} Trying backup...")
        state = load_backup_state()

    # Set up GitHub persistence
    gh = setup_storage()
    if gh:
        log.info("GitHub storage configured. Pulling latest state files...")
        gh.pull_file("drop_cred_scores.json",   "drop_cred_scores.json")
        gh.pull_file("drop_cred_scanned.json",  "drop_cred_scanned.json")
        gh.pull_file("playlist_state.json",     "playlist_state.json")
        gh.pull_file("pending_submissions.json","pending_submissions.json")
        log.info("State files pulled from GitHub.")
    else:
        log.warning("GitHub storage not configured — state will not persist across redeployments.")

    scores  = load_scores()
    scanned = load_scanned()

    # Load pending submissions
    _load_pending_submissions(submissions, gh)

    # Log submission system status
    if SUBMISSIONS_CHANNEL_ID and PENDING_CHANNEL_ID:
        log.info(
            f"Submission system active. "
            f"#song-submissions: {SUBMISSIONS_CHANNEL_ID}, "
            f"#pending-approval: {PENDING_CHANNEL_ID}, "
            f"Trusted role: {TRUSTED_ROLE_ID or 'not set'}"
        )
    else:
        log.warning(
            "Submission system not fully configured. "
            "Set SUBMISSIONS_CHANNEL_ID and PENDING_CHANNEL_ID to enable."
        )

    discord.post_to_alerts(
        f"✅ Bot started at {now_str()}\n"
        f"Checking playlist every {CHECK_INTERVAL // 60} min. "
        f"Scoring every {SCORE_SCAN_INTERVAL // 60} min. "
        f"Submission system: {'active' if SUBMISSIONS_CHANNEL_ID else 'not configured'}."
    )

    last_heartbeat       = time.time()
    last_success_time    = time.time()
    last_score_scan      = 0
    last_leaderboard     = 0
    consecutive_failures = 0
    current_tracks       = {}  # kept in sync for submission duplicate checks

    while True:
        # ── Spotify playlist check ────────────────────────────────────────────
        try:
            log.info("-" * 40)
            log.info(f"Checking playlist at {now_str()}...")

            previous_count = len(state) if state else None
            tracks = spotify.get_playlist_tracks(previous_count=previous_count)
            current_tracks = tracks  # keep reference for submission checks

            for warning in getattr(spotify, "_last_warnings", []):
                discord.post_to_alerts(f"⚠️ Spotify parser warning: {warning}")
            if getattr(spotify, "_last_structure_changed", False):
                discord.post_to_alerts(
                    "⚠️ Spotify API structure changed — parser adapted automatically."
                )

            if state is None:
                log.info(f"First run: {len(tracks)} songs on Spotify.")
                state = initialize_state(LEGACY_TRACK_IDS, tracks)
                save_state(state)
                discord.post_to_alerts(
                    f"✅ Bot initialized at {now_str()}\n"
                    f"{len(state)} songs loaded."
                )
            else:
                current_ids = set(tracks.keys())
                known_ids   = set(state.keys())
                added       = current_ids - known_ids
                removed     = known_ids   - current_ids

                if len(removed) > 10:
                    raise StateError(
                        f"Would remove {len(removed)} songs at once — suspicious. Skipping."
                    )

                if not added and not removed:
                    log.info("No changes detected.")
                else:
                    log.info(f"{len(added)} added, {len(removed)} removed.")
                    for track_id in added:
                        handle_added_song(track_id, tracks[track_id], discord, users, state, scores, scanned)
                    for track_id in list(removed):
                        handle_removed_song(track_id, state[track_id], discord)
                        del state[track_id]

                save_state(state)
                save_scores(scores)

            last_success_time    = time.time()
            consecutive_failures = 0

        except SpotifyTokenExpiredError as e:
            # Token expired mid-run — alert and exit cleanly (do NOT retry)
            log.error(f"Spotify refresh token expired during run: {e}")
            discord.post_to_alerts(
                f"🔴 **ACTION REQUIRED — Spotify token expired**\n"
                f"{e}\n\n"
                f"Steps to fix:\n"
                f"1. On your computer, run: `python get_spotify_token.py`\n"
                f"2. Upload the new `spotify_token.json` to GitHub\n"
                f"3. Railway will redeploy automatically\n\n"
                f"The bot is shutting down until the token is replaced."
            )
            sys.exit(1)

        except SpotifyError as e:
            consecutive_failures += 1
            log.error(f"Spotify error: {e}")
            discord.post_to_alerts(f"⚠️ Spotify error #{consecutive_failures}: {e}")
        except StateError as e:
            consecutive_failures += 1
            log.error(f"State error: {e}")
            discord.post_to_alerts(f"⚠️ State error #{consecutive_failures}: {e}")
        except DiscordError as e:
            consecutive_failures += 1
            log.error(f"Discord error: {e}")
        except Exception as e:
            consecutive_failures += 1
            log.error(f"Unexpected error: {e}", exc_info=True)
            discord.post_to_alerts(f"⚠️ Unexpected error #{consecutive_failures}: {e}")

        if time.time() - last_success_time > 1800:
            discord.post_to_alerts(
                f"🚨 No successful check in 30+ minutes. Failures: {consecutive_failures}"
            )

        # ── Song submission processing ─────────────────────────────────────────
        if SUBMISSIONS_CHANNEL_ID and PENDING_CHANNEL_ID:
            try:
                submissions.check_new_submissions(GUILD_ID, current_tracks)
                submissions.check_pending_reactions(current_tracks)
                _save_pending_submissions(submissions, gh)
            except Exception as e:
                log.error(f"Submission system error: {e}", exc_info=True)
                discord.post_to_alerts(f"⚠️ Submission system error: {e}")

        # ── Activity scoring scan ─────────────────────────────────────────────
        log.info(f"Scoring check: GUILD_ID={bool(GUILD_ID)}, time_since_scan={int(time.time() - last_score_scan)}s, interval={SCORE_SCAN_INTERVAL}s")
        if GUILD_ID and time.time() - last_score_scan > SCORE_SCAN_INTERVAL:
            try:
                log.info("Scanning Discord activity for scoring...")
                pe, be, unknown_ids = scanner.scan_all(
                    guild_id              = GUILD_ID,
                    forum_channel_id      = FORUM_CHANNEL_ID,
                    challenges_channel_id = CHALLENGES_CHANNEL_ID,
                    scores                = scores,
                    scanned               = scanned,
                )
                save_scores(scores)
                save_scanned(scanned)

                if gh:
                    gh.push_file("drop_cred_scores.json",  "drop_cred_scores.json",  "Scoring scan complete")
                    gh.push_file("drop_cred_scanned.json", "drop_cred_scanned.json", "Scoring scan complete")

                for display_name, new_badge in be:
                    announce_badge(discord, display_name, new_badge)
                    time.sleep(1)

                for discord_id in unknown_ids:
                    discord.post_to_alerts(
                        f"⚠️ Unknown Discord user ID `{discord_id}` is active in the server.\n"
                        f"Add them to user_lookup.py so their activity can be scored."
                    )

                last_score_scan = time.time()
                log.info(f"Scoring scan complete. {len(pe)} point events.")
            except Exception as e:
                log.error(f"Scoring scan error: {e}", exc_info=True)
                discord.post_to_alerts(f"⚠️ Scoring scan error: {e}")

        # ── Leaderboard update ────────────────────────────────────────────────
        if time.time() - last_leaderboard > LEADERBOARD_INTERVAL:
            try:
                update_pinned_leaderboard(DISCORD_BOT_TOKEN, scores)
                post_weekly_announcement(DISCORD_BOT_TOKEN, scores)
                last_leaderboard = time.time()
            except Exception as e:
                log.error(f"Leaderboard error: {e}")
                discord.post_to_alerts(f"⚠️ Leaderboard update error: {e}")

        # ── Daily heartbeat ───────────────────────────────────────────────────
        if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
            discord.post_to_alerts(
                f"💓 Bot heartbeat — {now_str()}\n"
                f"Playlist: {len(state) if state else 0} songs. "
                f"Scores tracked for {len(scores)} users. "
                f"Pending submissions: {len(submissions.pending)}."
            )
            last_heartbeat = time.time()

        time.sleep(CHECK_INTERVAL)


# ── Pending submission persistence ────────────────────────────────────────────

def _load_pending_submissions(submissions, gh):
    """Load pending submissions from GitHub or local file."""
    import json, os
    filename = "pending_submissions.json"
    try:
        if os.path.exists(filename):
            with open(filename) as f:
                data = json.load(f)
            submissions.load_pending(data)
            log.info(f"Loaded {len(submissions.pending)} pending submissions.")
        else:
            log.info("No pending submissions file found — starting fresh.")
    except Exception as e:
        log.warning(f"Could not load pending submissions (non-fatal): {e}")
        submissions.pending = {}

def _save_pending_submissions(submissions, gh):
    """Save pending submissions to local file and optionally GitHub."""
    import json
    filename = "pending_submissions.json"
    try:
        with open(filename, "w") as f:
            json.dump(submissions.dump_pending(), f, indent=2)
        if gh and submissions.pending:
            gh.push_file(filename, filename, "Update pending submissions")
    except Exception as e:
        log.warning(f"Could not save pending submissions: {e}")


if __name__ == "__main__":
    main()
