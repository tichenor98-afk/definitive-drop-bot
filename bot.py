"""
bot.py
Main bot loop. Coordinates Spotify, Discord, state, and user lookup.
Checks the playlist every 10 minutes and posts changes to Discord.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone

from spotify_client import SpotifyClient, SpotifyError
from discord_client import DiscordClient, DiscordError
from state_manager  import (
    load_state, save_state, load_backup_state,
    initialize_state, validate_state, StateError,
)
from user_lookup import UserLookup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-10s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bot")

# ── Config (all from Railway environment variables) ───────────────────────────
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

CHECK_INTERVAL        = int(os.environ.get("CHECK_INTERVAL", "600"))
HEARTBEAT_INTERVAL    = 86400  # 24 hours
TOKEN_FILE            = "spotify_token.json"

# Track IDs that existed before this bot was deployed.
# These songs already have posts in Discord that we didn't create,
# so we don't know their thread IDs. Bot knows about them but
# cannot comment on their posts if removed.
LEGACY_TRACK_IDS = set(["7lQy8vI73IL4Wft8I4eA5Z", "0lJK5ZmN9K4IaEi6QHj5W8", "2gG7E5OZi5D5QLRIctv63z", "6uWV09syluMJlYbAHgLRhn", "1nYg1Ac4xsGBkmTvhXDzG2", "5A9mGMMsmySIZmBH6icc4B", "01Oi7A4u4knAEPqylXM9s8", "6H3kDe7CGoWYBabAeVWGiD", "35q1B8x7zRsITx6SxcWK67", "5CIe9u7lex3fxPmwWqrjo3", "7rBMZvgeWnOTHWUh3Pvw51", "0wZurfElW3yOHscb38vBL8", "0m1DJ5Jkv3kdnGrcZsJFmC", "5pK4elvBpzeAk8amFG3NVN", "0whFZ2qMsiUMkQOxsfRy5p", "78sUOio7Q63zyraK2auLla", "0BqQWfhMrkpRAUCbdfdHUC", "4dT3qLUU6fFUmomLzk2cUA", "5ynO8cYFjDwELIZfFHHeYe", "2fUesvrGtDQ37bUz30nMak", "1rmtygBvOF8Wb1OwVMAyaE", "0P2vAvvWni2tNXOdbH3JFk", "0xeBC6N81ZBYDtxuBFGSuO", "750wm5pwuAQfnSLX8mxa5f", "6QewNVIDKdSl8Y3ycuHIei", "3aKhLm5mONfAtS1NZXG8f4", "2lp0PO2D90zcFWy8toVqgn", "0hSUqAj87s0gHUS8U4TRIF", "1dfHpGeaXunLRNvzSZOZtc", "4E5xVW505akJX0wcKj8Mpd", "60QLLec3yKDwloXCyummPy", "4EchqUKQ3qAQuRNKmeIpnf", "43G3McVkRa8V7oGQzfQuRr", "3lSrLqwpS23lMqhtDierCq", "1h2xVEoJORqrg71HocgqXd", "2SIVPuWP84mPNhF0Ns9nWC", "6zsk6uF3MxfIeHPlubKBvR", "31er9IGsfFbwqy1pH4aiTP", "2NVpYQqdraEcQwqT7GhUkh", "0bJKesHl9raebAYBpQp3wv", "0L7zm6afBEtrNKo6C6Gj08", "6QyBIZEvs11K9lKjyLYtv6", "5CeL9C3bsoe4yzYS1Qz8cw", "07p7PALHp6ZcD5tmlbO94N", "41eFwwTvEhuBgE4SAXxRGd", "69MwNXryg6NT1lV7buN7U7", "0wZYfxL16dtfTvxFpWTB7L", "2IKd8ozOHYuVqrYJ0tqghP", "50fGkq9l9Zsn1x7C8GKIYr", "0uppYCG86ajpV2hSR3dJJ0", "6dmiV9JGjv4vGgLwEZTaOI", "4v2rkl1mC3zVAz0nXMx9r4", "2TVutF2Xy9R6PLVQ5jEEUs", "4KxhIoBjdvaIGA5U6a1c3o", "0LtsuNRz3IMRrHCYO9fKRk", "4jQDaI7FRGaDB0llURpnNf", "0z8oPUM05RZBJ1A1dXPsSs", "3CIOopLwvyMvXk97ZEksKO", "4xVXe1VS5zlQyECVk6GRrL", "54bm2e3tk8cliUz3VSdCPZ", "154gL4Xb5AsreMkcDlVFYS", "1672RT45nXNUb28fzzPxn8", "1a19jsjG2DvbN1fVJonKUU", "3fkPMWQ6cBNBLuFcPyMS8s", "4E0P1xs3JNmsNr5c5nFTZJ", "6CxQsBfTmhx0RsoJoV8hH7", "3agtg0x11wPvLIWkYR39nZ", "5UWwZ5lm5PKu6eKsHAGxOk", "6J5kc12BW5HuP3d7C3vvx8", "27BgDmciSjoxTG0almHTpZ", "0N3W5peJUQtI4eyR6GJT5O", "4fjWStUaP7aXdT0d3YxvPo", "2gdtLnVGGg80Kj9GiqP0vH", "06h9kk12VjJ2bqcBc6IScR", "5sFDReWLrZHLFZFjHsjUTS", "5fKZJHzJ9d3MADArbm9muW", "0bt3YJTupDqdTKpnFFgs7f", "6cr6UDpkjEaMQ80OjWqEBQ", "7k0UY4Kabh7SUHXowyfKj7", "2amzrvbxYiq8AxGntIiw5V", "20KSB3DRekMDCb31rY0ATd", "3gjHnylel3PTRpjS44ocqr", "7DD7eSuYSC5xk2ArU62esN", "5b1jZ9geGD4boxz24XgGPp", "033N3Mf87ODmORg6YO61cm", "7fcfNW0XxTWlwVlftzfDOR", "2id8E4WvczfKHB4LHI7Np3", "7qj6lBOB1QTgBmKedXuIbs", "2PpNgmrS9mAyrkRAwn6YPq", "1CM1wOqD2AIjt2MWd31LV2", "2V4Bc2I962j7acQj1N0PiQ", "2QSUyofqpGDCo026OPiTBQ", "53DfWyh0C0rJUGpsmtdRc1", "3YuaBvuZqcwN3CEAyyoaei", "5EicljVZKVOo2LZHREtWmQ", "0xaNdYwK8ZF3cHSjraQGC0", "3QZ7uX97s82HFYSmQUAN1D", "4pzcMiIkEv8cOe5vD7xfGq", "2VGf3YQ6Zfzb6YyDatYAcY", "10V8XpuyMoEcSMfM79WDET", "0hDQV9X1Da5JrwhK8gu86p", "2854fjg3reX87rDKe6Bk73", "4C7Ss9bTPOWJMh3rarF1mN", "0ObrXLrfrqJUNc8RfmIBHP", "0Dw9z44gXhplDh5HCWZIxP", "2Bux4j9el8GFOrvAE8dMA3", "4VwPsMcRt1HPVKIdcwY9Uj", "2AdRSHeYmDGMrgIfiS2w7K", "5Cr3dgYZKJrUTJjy2bEaYa", "006yvCdaWUS79qp2Ip3Hdl", "26Kw6zBo3Uy98q5LTlFfVJ", "1H4idkmruFoJBg1DvUv2tY", "54bO2CHOgGN44oWmAqib0I"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_date(iso):
    """Format ISO date string to readable date."""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%B %d, %Y")
    except Exception:
        return iso

def now_str():
    return datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

def now_date():
    return datetime.now(timezone.utc).strftime("%B %d, %Y")

# ── Main logic ────────────────────────────────────────────────────────────────

def handle_added_song(track_id, track, discord, users, state):
    """Handle a newly added song: create Discord post and log it."""
    name      = track["name"]
    artist    = track["artist"]
    url       = track["url"]
    added_by  = users.get_name(track.get("added_by", ""))
    added_at  = fmt_date(track.get("added_at", "")) or now_date()

    log.info(f"New song: {name} -- {artist} (added by {added_by})")

    # Alert if this is an unknown user
    if track.get("added_by") and users.is_unknown(track.get("added_by", "")):
        discord.post_to_alerts(
            f"⚠️ Unknown Spotify user `{track['added_by']}` added a song.\n"
            f"Song: {name} by {artist}\n"
            f"Add them to the name lookup sheet so their name shows correctly."
        )

    # 1. Create forum post in #the-playlist
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

    # 2. Log in #playlist-updates
    try:
        discord.post_to_updates(
            f"✅ **Song Added**\n"
            f"Track: {name}\n"
            f"Artist: {artist}\n"
            f"Added by: {added_by}\n"
            f"Added: {added_at}"
        )
    except DiscordError as e:
        log.error(f"Failed to post to #playlist-updates for {name}: {e}")
        discord.post_to_alerts(f"⚠️ Failed to post addition of {name} to #playlist-updates. Error: {e}")

    # Update state
    state[track_id] = {
        "thread_id": thread_id,
        "name":      name,
        "artist":    artist,
    }
    time.sleep(1)


def handle_removed_song(track_id, song_state, discord):
    """Handle a removed song: comment on its post and log it."""
    name      = song_state.get("name", track_id)
    artist    = song_state.get("artist", "")
    thread_id = song_state.get("thread_id")
    removed   = now_str()
    removed_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    log.info(f"Removed: {name} -- {artist}")

    # 1. Comment on the song's post in #the-playlist (if we have the thread ID)
    if thread_id:
        commented = discord.comment_on_post(thread_id, f"Removed {removed_date}")
        if not commented:
            discord.post_to_alerts(
                f"⚠️ Could not comment on Discord post for removed song: {name} by {artist}\n"
                f"Thread ID: {thread_id}"
            )
    else:
        # This is a legacy song — we don't have its thread ID
        log.info(f"No thread ID for {name} — this is a legacy song. Skipping comment.")

    time.sleep(1)

    # 2. Log in #playlist-updates
    try:
        discord.post_to_updates(
            f"❌ **Song Removed**\n"
            f"Track: {name}\n"
            f"Artist: {artist}\n"
            f"Removed: {removed_date}"
        )
    except DiscordError as e:
        log.error(f"Failed to post removal of {name} to #playlist-updates: {e}")
        discord.post_to_alerts(f"⚠️ Failed to post removal of {name} to #playlist-updates. Error: {e}")

    time.sleep(1)


def check_for_changes(spotify, discord, users, state):
    """
    Core logic: compare current Spotify playlist to known state.
    Returns updated state.
    """
    previous_count = len(state) if state else None

    try:
        tracks = spotify.get_playlist_tracks(previous_count=previous_count)
    except SpotifyError as e:
        raise  # let the caller handle this

    # Validate before acting
    is_valid, reason = validate_state(state or {}, len(tracks))
    if state and not is_valid:
        raise StateError(f"State validation failed: {reason}")

    current_ids = set(tracks.keys())
    known_ids   = set(state.keys()) if state else set()

    added   = current_ids - known_ids
    removed = known_ids   - current_ids

    # Safety check: never remove more than 10 songs at once
    if len(removed) > 10:
        raise StateError(
            f"Bot would remove {len(removed)} songs at once. "
            f"This is suspicious. Skipping to prevent false removals."
        )

    if not added and not removed:
        log.info("No changes detected.")
        return state

    log.info(f"Changes detected: {len(added)} added, {len(removed)} removed.")

    # Handle additions
    for track_id in added:
        handle_added_song(track_id, tracks[track_id], discord, users, state)

    # Handle removals
    for track_id in removed:
        handle_removed_song(track_id, state[track_id], discord)
        del state[track_id]

    return state


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Definitive Drop Playlist Bot starting...")
    log.info("=" * 60)

    # Initialize clients
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
    users = UserLookup(USERS_SHEET_CSV_URL)

    # Test Discord connection on startup
    try:
        discord.test_connection()
    except DiscordError as e:
        log.error(f"Discord connection failed on startup: {e}")
        # Can't post alert since Discord is down, just exit and let Railway restart
        sys.exit(1)

    # Refresh Spotify token on startup
    try:
        spotify.refresh_access_token()
    except SpotifyError as e:
        log.error(f"Spotify token refresh failed on startup: {e}")
        discord.post_to_alerts(
            f"⚠️ Bot failed to start: Spotify token error.\n"
            f"Error: {e}\n"
            f"Run get_spotify_token.py to generate a new token."
        )
        sys.exit(1)

    # Load state
    try:
        state = load_state()
    except StateError as e:
        log.warning(f"State file problem: {e} Trying backup...")
        discord.post_to_alerts(f"⚠️ State file problem: {e} Attempting to load backup.")
        state = load_backup_state()
        if state is None:
            log.info("No valid state or backup. Will initialize on first check.")

    # Announce startup
    discord.post_to_alerts(
        f"✅ Bot started successfully at {now_str()}\n"
        f"Checking playlist every {CHECK_INTERVAL // 60} minutes."
    )

    last_heartbeat    = time.time()
    last_success_time = time.time()
    consecutive_failures = 0

    while True:
        try:
            log.info("-" * 40)
            log.info(f"Checking playlist at {now_str()}...")

            # Fetch tracks
            previous_count = len(state) if state else None
            tracks = spotify.get_playlist_tracks(previous_count=previous_count)

            # First run: initialize state
            if state is None:
                log.info(f"First run: {len(tracks)} songs on Spotify.")
                state = initialize_state(LEGACY_TRACK_IDS, tracks)
                save_state(state)
                discord.post_to_alerts(
                    f"✅ Bot initialized at {now_str()}\n"
                    f"{len(state)} songs loaded. Bot is now monitoring for changes."
                )
                last_success_time    = time.time()
                consecutive_failures = 0

            else:
                # Check for changes
                current_ids = set(tracks.keys())
                known_ids   = set(state.keys())
                added       = current_ids - known_ids
                removed     = known_ids   - current_ids

                # Safety: never remove more than 10 at once
                if len(removed) > 10:
                    raise StateError(
                        f"Would remove {len(removed)} songs at once — suspiciously high. "
                        f"Skipping this check."
                    )

                if not added and not removed:
                    log.info("No changes detected.")
                else:
                    log.info(f"{len(added)} added, {len(removed)} removed.")
                    for track_id in added:
                        handle_added_song(track_id, tracks[track_id], discord, users, state)
                    for track_id in list(removed):
                        handle_removed_song(track_id, state[track_id], discord)
                        del state[track_id]

                save_state(state)
                last_success_time    = time.time()
                consecutive_failures = 0

            # Daily heartbeat
            if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                discord.post_to_alerts(
                    f"💓 Bot heartbeat — {now_str()}\n"
                    f"Playlist has {len(state)} songs. Bot is running normally."
                )
                last_heartbeat = time.time()

        except SpotifyError as e:
            consecutive_failures += 1
            log.error(f"Spotify error: {e}")
            discord.post_to_alerts(
                f"⚠️ Spotify error (failure #{consecutive_failures}): {e}\n"
                f"Will retry in {CHECK_INTERVAL // 60} minutes."
            )

        except StateError as e:
            consecutive_failures += 1
            log.error(f"State error: {e}")
            discord.post_to_alerts(
                f"⚠️ State error (failure #{consecutive_failures}): {e}\n"
                f"No changes were posted. Will retry in {CHECK_INTERVAL // 60} minutes."
            )

        except DiscordError as e:
            consecutive_failures += 1
            log.error(f"Discord error: {e}")
            # Can't post alert if Discord is down
            if "401" in str(e) or "token" in str(e).lower():
                log.error("Discord token may be invalid. Bot cannot recover automatically.")

        except Exception as e:
            consecutive_failures += 1
            log.error(f"Unexpected error: {e}", exc_info=True)
            discord.post_to_alerts(
                f"⚠️ Unexpected error (failure #{consecutive_failures}): {e}\n"
                f"Will retry in {CHECK_INTERVAL // 60} minutes."
            )

        # Alert if no successful check in 30 minutes
        if time.time() - last_success_time > 1800:
            discord.post_to_alerts(
                f"🚨 Bot alert: No successful playlist check in 30+ minutes.\n"
                f"Last success: {datetime.fromtimestamp(last_success_time, tz=timezone.utc).strftime('%H:%M UTC')}\n"
                f"Consecutive failures: {consecutive_failures}"
            )

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
