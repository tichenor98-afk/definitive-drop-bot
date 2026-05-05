import os
import time
import json
import requests
from datetime import datetime, timezone

# ── CONFIG (set these as environment variables on Railway) ───────────────────
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID",     "962dc26019874f8781de1a133e126d9b")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "48a2c83b38ca4ee8b25fe71c05e7b211")
SPOTIFY_PLAYLIST_ID   = os.environ.get("SPOTIFY_PLAYLIST_ID",   "5Prn6P7pbsnLnzeWE3q7wS")
DISCORD_BOT_TOKEN     = os.environ.get("DISCORD_BOT_TOKEN",     "PASTE_YOUR_BOT_TOKEN_HERE")
FORUM_CHANNEL_ID      = os.environ.get("FORUM_CHANNEL_ID",      "1499885742095208599")
UPDATES_CHANNEL_ID    = os.environ.get("UPDATES_CHANNEL_ID",    "1501346456852758669")

CHECK_INTERVAL = 600  # seconds between checks (10 minutes)

STATE_FILE = "playlist_state.json"  # tracks known songs between runs
# ────────────────────────────────────────────────────────────────────────────

USER_MAP = {
    "1244544596":                    "Kimberly DeLiz",
    "nbd69oy9yijanj8zyj9uuioub":     "Marianne Hartman Tichenor",
    "tichenor.tichenor":             "Colette Tichenor",
    "31pght73z6jbr7yxnbveogsceyzi":  "Christopher Tichenor",
    "31j6esa7qom5yvr5htfvolixk6mu":  "Brett Szudy",
    "1246961212":                    "Scott Tichenor",
    "1214967802":                    "Dennis McNulty",
}

def get_real_name(spotify_id: str) -> str:
    raw = spotify_id.replace("spotify:user:", "").strip()
    return USER_MAP.get(raw, raw)

def format_datetime(iso: str) -> str:
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        return iso

def format_date_only(iso: str) -> str:
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%B %d, %Y")
    except Exception:
        return iso

# ── SPOTIFY ──────────────────────────────────────────────────────────────────

def get_spotify_token():
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
    )
    return r.json()["access_token"]

def get_playlist_tracks(token):
    """Returns dict of track_id -> track info for all tracks in playlist."""
    tracks = {}
    url = f"https://api.spotify.com/v1/playlists/{SPOTIFY_PLAYLIST_ID}/tracks"
    headers = {"Authorization": f"Bearer {token}"}
    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        for item in data.get("items", []):
            if not item or not item.get("track"):
                continue
            track = item["track"]
            track_id = track["id"]
            added_by_id = item.get("added_by", {}).get("id", "unknown")
            tracks[track_id] = {
                "id":         track_id,
                "name":       track["name"],
                "artist":     ", ".join(a["name"] for a in track["artists"]),
                "added_by":   added_by_id,
                "added_at":   item.get("added_at", ""),
                "url":        track["external_urls"]["spotify"],
            }
        url = data.get("next")
    return tracks

# ── STATE ─────────────────────────────────────────────────────────────────────

def load_state():
    """Load saved state: known track IDs and their Discord thread IDs."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}   # {track_id: {"thread_id": "...", "name": "...", "artist": "..."}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── DISCORD ───────────────────────────────────────────────────────────────────

DISCORD_HEADERS = lambda: {
    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    "Content-Type": "application/json",
}

def create_forum_post(title, content):
    """Create a new post in the forum channel. Returns thread_id or None."""
    r = requests.post(
        f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}/threads",
        json={"name": title, "message": {"content": content}},
        headers=DISCORD_HEADERS(),
    )
    if r.status_code in (200, 201):
        return r.json()["id"]
    else:
        print(f"  Forum post error {r.status_code}: {r.text}")
        return None

def post_message(channel_id, content):
    """Post a message to a regular text channel."""
    r = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        json={"content": content},
        headers=DISCORD_HEADERS(),
    )
    if r.status_code not in (200, 201):
        print(f"  Message error {r.status_code}: {r.text}")

def post_thread_message(thread_id, content):
    """Post a message inside an existing forum thread."""
    r = requests.post(
        f"https://discord.com/api/v10/channels/{thread_id}/messages",
        json={"content": content},
        headers=DISCORD_HEADERS(),
    )
    if r.status_code not in (200, 201):
        print(f"  Thread message error {r.status_code}: {r.text}")

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def check_for_changes():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking playlist...")

    token  = get_spotify_token()
    tracks = get_playlist_tracks(token)
    state  = load_state()

    current_ids = set(tracks.keys())
    known_ids   = set(state.keys())

    added   = current_ids - known_ids
    removed = known_ids   - current_ids

    # ── Handle added songs ────────────────────────────────────────────────────
    for track_id in added:
        t        = tracks[track_id]
        name     = t["name"]
        artist   = t["artist"]
        added_by = get_real_name(t["added_by"])
        added_at = format_date_only(t["added_at"])
        url      = t["url"]

        print(f"  ➕ New song: {name} — {artist} (added by {added_by})")

        post_title = f"{name} — {artist}"
        content = (
            f"🎵 **{name}**\n"
            f"👤 **Artist:** {artist}\n"
            f"➕ **Added by:** {added_by}\n"
            f"📅 **Added:** {added_at}\n"
            f"🔗 {url}"
        )

        thread_id = create_forum_post(post_title, content)
        time.sleep(2)

        update_msg = (
            f"✅ **New song added to the playlist!**\n"
            f"🎵 {name} — {artist}\n"
            f"➕ Added by: {added_by}\n"
            f"📅 {added_at}"
        )
        post_message(UPDATES_CHANNEL_ID, update_msg)

        state[track_id] = {
            "thread_id": thread_id,
            "name":      name,
            "artist":    artist,
        }
        time.sleep(2)

    # ── Handle removed songs ──────────────────────────────────────────────────
    for track_id in removed:
        s         = state[track_id]
        name      = s["name"]
        artist    = s["artist"]
        thread_id = s.get("thread_id")
        removed_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

        print(f"  ❌ Removed: {name} — {artist}")

        if thread_id:
            removal_note = (
                f"⚠️ **This song was removed from the playlist.**\n"
                f"📅 Removed: {removed_at}"
            )
            post_thread_message(thread_id, removal_note)
            time.sleep(2)

        update_msg = (
            f"❌ **Song removed from the playlist.**\n"
            f"🎵 {name} — {artist}\n"
            f"📅 Removed: {removed_at}"
        )
        post_message(UPDATES_CHANNEL_ID, update_msg)

        del state[track_id]
        time.sleep(2)

    if not added and not removed:
        print("  No changes detected.")

    save_state(state)

def main():
    print("Playlist bot starting...")
    while True:
        try:
            check_for_changes()
        except Exception as e:
            print(f"  Error: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
