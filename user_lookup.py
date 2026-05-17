"""
user_lookup.py

Central identity registry for The Definitive Drop.
Maps Spotify IDs, Discord IDs, and display names together.

HOW TO ADD A NEW USER:
1. Add a new entry to USER_REGISTRY below
2. Fill in as many fields as you know (spotify_id and/or discord_id)
3. Save and upload user_lookup.py to GitHub
4. Railway will redeploy automatically

Fields:
  display_name  - shown in Discord posts and leaderboard
  spotify_id    - their Spotify user ID (from bot-alerts when they add a song)
  discord_id    - their Discord user ID (right-click name -> Copy User ID)
  discord_handle - their Discord username (for reference only)
"""

import logging

log = logging.getLogger("users")

# ── User registry ─────────────────────────────────────────────────────────────
USER_REGISTRY = [
    {
        "display_name":    "Kimberly DeLiz",
        "spotify_id":      "1244544596",
        "discord_id":      "959078111746592788",
        "discord_handle":  "kimberlydeez",
    },
    {
        "display_name":    "MHT",
        "spotify_id":      "nbd69oy9yijanj8zyj9uuioub",
        "discord_id":      "636545391973892098",
        "discord_handle":  "mht3k",
        "aliases":         ["Marianne Hartman Tichenor"],
    },
    {
        "display_name":    "Colette Tichenor",
        "spotify_id":      "tichenor.tichenor",
        "discord_id":      "1042133329127940237",
        "discord_handle":  "ctich6490",
    },
    {
        "display_name":    "Christopher Tichenor",
        "spotify_id":      "31pght73z6jbr7yxnbveogsceyzi",
        "discord_id":      "563162903327408150",
        "discord_handle":  "ctichenor",
    },
    {
        "display_name":    "Brett Szudy",
        "spotify_id":      "31j6esa7qom5yvr5htfvolixk6mu",
        "discord_id":      "796850541593755658",
        "discord_handle":  "szude",
    },
    {
        "display_name":    "Scott Tichenor",
        "spotify_id":      "1246961212",
        "discord_id":      "517866322894520321",
        "discord_handle":  "scott_pi4429",
    },
    {
        "display_name":    "Dennis McNulty",
        "spotify_id":      "1214967802",
        "discord_id":      "1188906992157347911",
        "discord_handle":  "dlm9700",
    },
    {
        "display_name":    "Zander Tichenor",
        "spotify_id":      "22dackqzio7lltn5bpsrjp3aq",
        "discord_id":      None,   # not in Discord yet
        "discord_handle":  None,
    },
    {
        "display_name":    "Angelina McNulty",
        "spotify_id":      "angelinamc99",
        "discord_id":      "1502725647213006922",
        "discord_handle":  "angelina08022",
    },
    {
        "display_name":    "Michael McNulty",
        "spotify_id":      "31nz2zx2v7ok3fxnytyvaawnni4u",
        "discord_id":      "613117187523084324",
        "discord_handle":  "mcshrooms",
    },
    {
        "display_name":    "Dennis Hartman",
        "spotify_id":      "d-roka",
        "discord_id":      "1500117178396049501",
        "discord_handle":  "dennishartmannola",
    },
    {
        "display_name":    "Conrad Tichenor",
        "spotify_id":      None,   # no Spotify yet
        "discord_id":      "546879179384291357",
        "discord_handle":  "dense0170",
    },
]
# ─────────────────────────────────────────────────────────────────────────────

# Bot IDs to exclude from all scoring and activity tracking
BOT_IDS = {
    "1499887874584219779",  # Playlist Bot
}

# Build lookup indexes at module load time
_by_spotify  = {}
_by_discord  = {}
_by_display  = {}

for _user in USER_REGISTRY:
    if _user.get("spotify_id"):
        _by_spotify[_user["spotify_id"]] = _user
    if _user.get("discord_id"):
        _by_discord[str(_user["discord_id"])] = _user
    _by_display[_user["display_name"].lower()] = _user
    # Index aliases so they can be resolved to display names
    for _alias in _user.get("aliases", []):
        _by_display[_alias.lower()] = _user


class UserLookup:
    def __init__(self, sheet_csv_url=None):
        log.info(f"User registry loaded: {len(USER_REGISTRY)} users.")
        for u in USER_REGISTRY:
            log.info(f"  {u['display_name']} | spotify={u.get('spotify_id')} | discord={u.get('discord_id')}")

    def get_name_by_spotify(self, spotify_id):
        """Get display name from Spotify ID. Returns ID if not found."""
        if not spotify_id:
            return "Unknown"
        clean = spotify_id.replace("spotify:user:", "").strip()
        user = _by_spotify.get(clean)
        if user:
            return user["display_name"]
        log.warning(f"Unknown Spotify ID: '{clean}'")
        return clean

    # Keep old method name for compatibility
    def get_name(self, spotify_id):
        return self.get_name_by_spotify(spotify_id)

    def get_name_by_discord(self, discord_id):
        """Get display name from Discord ID. Returns None if not found."""
        user = _by_discord.get(str(discord_id))
        return user["display_name"] if user else None

    def is_unknown_spotify(self, spotify_id):
        """True if Spotify ID is not in registry."""
        if not spotify_id:
            return True
        clean = spotify_id.replace("spotify:user:", "").strip()
        return clean not in _by_spotify

    # Keep old method name for compatibility
    def is_unknown(self, spotify_id):
        return self.is_unknown_spotify(spotify_id)

    def is_unknown_discord(self, discord_id):
        """True if Discord ID is not in registry and not a bot."""
        did = str(discord_id)
        if did in BOT_IDS:
            return False
        return did not in _by_discord

    def is_bot(self, discord_id):
        """True if this Discord ID belongs to a bot."""
        return str(discord_id) in BOT_IDS

    def get_all_users(self):
        """Return full registry list."""
        return USER_REGISTRY

    def get_display_names(self):
        """Return sorted list of all display names."""
        return sorted(u["display_name"] for u in USER_REGISTRY)
