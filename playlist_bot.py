import os
import time
import json
import requests
from datetime import datetime, timezone

# ── CONFIG ───────────────────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID",     "962dc26019874f8781de1a133e126d9b")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "48a2c83b38ca4ee8b25fe71c05e7b211")
SPOTIFY_PLAYLIST_ID   = os.environ.get("SPOTIFY_PLAYLIST_ID",   "5Prn6P7pbsnLnzeWE3q7wS")
DISCORD_BOT_TOKEN     = os.environ.get("DISCORD_BOT_TOKEN",     "MTQ5OTg4Nzg3NDU4NDIxOTc3OQ.GuP6jl.yepPTEuOKBL9o4xZBmEaUqwsqwPikWQ_UBvn_M")
FORUM_CHANNEL_ID      = os.environ.get("FORUM_CHANNEL_ID",      "1499885742095208599")
UPDATES_CHANNEL_ID    = os.environ.get("UPDATES_CHANNEL_ID",    "1501346456852758669")

CHECK_INTERVAL = 600
STATE_FILE     = "playlist_state_v2.json"
TOKEN_FILE     = "spotify_token.json"
# ─────────────────────────────────────────────────────────────────────────────

def get_spotify_token():
    print(f"  Looking for token file at: {os.path.abspath(TOKEN_FILE)}")
    print(f"  Token file exists: {os.path.exists(TOKEN_FILE)}")
    print(f"  Files in current dir: {os.listdir('.')}")

    with open(TOKEN_FILE) as f:
        data = json.load(f)
    refresh_token = data["refresh_token"]
    print(f"  Refresh token found (first 10 chars): {refresh_token[:10]}...")

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
    )
    result = r.json()
    print(f"  Token response keys: {list(result.keys())}")

    if "access_token" not in result:
        raise Exception(f"Spotify token refresh error: {result}")

    if "refresh_token" in result:
        data["refresh_token"] = result["refresh_token"]
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f)

    return result["access_token"]

def get_playlist_tracks(token):
    tracks = {}
    url = f"https://api.spotify.com/v1/playlists/{SPOTIFY_PLAYLIST_ID}/items"
    headers = {"Authorization": f"Bearer {token}"}
    print(f"  Fetching: {url}")
    while url:
        r = requests.get(url, headers=headers)
        print(f"  Response status: {r.status_code}")
        data = r.json()
        if "error" in data:
            raise Exception(f"Spotify API error: {data['error']}")
        for item in data.get("items", []):
            if not item or not item.get("track"):
                continue
            track = item["track"]
            if not track.get("id"):
                continue
            track_id = track["id"]
            tracks[track_id] = {
                "id":     track_id,
                "name":   track["name"],
                "artist": ", ".join(a["name"] for a in track["artists"]),
                "url":    track["external_urls"]["spotify"],
            }
        url = data.get("next")
    return tracks

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def discord_headers():
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

def create_forum_post(title, content):
    r = requests.post(
        f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}/threads",
        json={"name": title, "message": {"content": content}},
        headers=discord_headers(),
    )
    if r.status_code in (200, 201):
        return r.json()["id"]
    else:
        print(f"  Forum post error {r.status_code}: {r.text}")
        return None

def post_message(channel_id, content):
    r = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        json={"content": content},
        headers=discord_headers(),
    )
    if r.status_code not in (200, 201):
        print(f"  Message error {r.status_code}: {r.text}")

def post_thread_message(thread_id, content):
    r = requests.post(
        f"https://discord.com/api/v10/channels/{thread_id}/messages",
        json={"content": content},
        headers=discord_headers(),
    )
    if r.status_code not in (200, 201):
        print(f"  Thread message error {r.status_code}: {r.text}")

def check_for_changes():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking playlist...")

    token  = get_spotify_token()
    tracks = get_playlist_tracks(token)
    state  = load_state()

    current_ids = set(tracks.keys())
    known_ids   = set(state.keys())

    added   = current_ids - known_ids
    removed = known_ids   - current_ids

    for track_id in added:
        t      = tracks[track_id]
        name   = t["name"]
        artist = t["artist"]
        url    = t["url"]
        today  = datetime.now(timezone.utc).strftime("%B %d, %Y")

        print(f"  + New song: {name} -- {artist}")

        thread_id = create_forum_post(
            f"{name} -- {artist}",
            f"🎵 **{name}**\n👤 **Artist:** {artist}\n📅 **Added:** {today}\n🔗 {url}"
        )
        time.sleep(2)

        post_message(
            UPDATES_CHANNEL_ID,
            f"✅ **New song added!**\n🎵 {name} -- {artist}\n📅 {today}"
        )

        state[track_id] = {"thread_id": thread_id, "name": name, "artist": artist}
        time.sleep(2)

    for track_id in removed:
        s          = state[track_id]
        name       = s["name"]
        artist     = s["artist"]
        thread_id  = s.get("thread_id")
        removed_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

        print(f"  - Removed: {name} -- {artist}")

        if thread_id:
            post_thread_message(
                thread_id,
                f"⚠️ **This song was removed from the playlist.**\n📅 Removed: {removed_at}"
            )
            time.sleep(2)

        post_message(
            UPDATES_CHANNEL_ID,
            f"❌ **Song removed.**\n🎵 {name} -- {artist}\n📅 Removed: {removed_at}"
        )

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
