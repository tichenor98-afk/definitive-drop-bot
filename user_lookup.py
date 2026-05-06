"""
user_lookup.py

Maps Spotify user IDs to display names.

HOW TO ADD A NEW USER:
1. Get their Spotify user ID (it appears in bot-alerts when they add a song)
2. Add a new line to USER_MAP below in the format:
       "their_spotify_id": "Their Display Name",
3. Save and upload user_lookup.py to GitHub
4. Railway will redeploy automatically within a minute

No other changes needed.
"""

import logging

log = logging.getLogger("users")

# ── User map: Spotify ID -> Display Name ──────────────────────────────────────
# Add new users here when they join the playlist.
USER_MAP = {
    "1244544596":                    "Kimberly DeLiz",
    "nbd69oy9yijanj8zyj9uuioub":     "MHT",
    "tichenor.tichenor":             "Colette Tichenor",
    "31pght73z6jbr7yxnbveogsceyzi":  "Christopher Tichenor",
    "31j6esa7qom5yvr5htfvolixk6mu":  "Brett Szudy",
    "1246961212":                    "Scott Tichenor",
    "1214967802":                    "Dennis McNulty",
    "d-roka":                        "Dennis Hartman",
}
# ─────────────────────────────────────────────────────────────────────────────


class UserLookup:
    def __init__(self, sheet_csv_url=None):
        # sheet_csv_url kept for API compatibility but not used
        # User data is hardcoded above for reliability
        log.info(f"User lookup initialized with {len(USER_MAP)} users.")
        for uid, name in USER_MAP.items():
            log.info(f"  {uid} -> {name}")

    def get_name(self, spotify_id):
        """
        Look up a Spotify user ID and return their display name.
        Returns the display name, or the raw ID if not found.
        """
        if not spotify_id:
            return "Unknown"

        clean_id = spotify_id.replace("spotify:user:", "").strip()
        name = USER_MAP.get(clean_id)

        if name:
            return name

        log.warning(f"User ID not in USER_MAP: '{clean_id}'")
        return clean_id

    def is_unknown(self, spotify_id):
        """Returns True if this user ID is not in USER_MAP."""
        if not spotify_id:
            return True
        clean_id = spotify_id.replace("spotify:user:", "").strip()
        return clean_id not in USER_MAP
