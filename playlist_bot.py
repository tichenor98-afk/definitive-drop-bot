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
STATE_FILE     = "runtime_state.json"
TOKEN_FILE     = "spotify_token.json"
# ─────────────────────────────────────────────────────────────────────────────

# All songs known at launch — bot will not post or flag these
INITIAL_KNOWN_IDS = [
  "7lQy8vI73IL4Wft8I4eA5Z",
  "0lJK5ZmN9K4IaEi6QHj5W8",
  "2gG7E5OZi5D5QLRIctv63z",
  "6uWV09syluMJlYbAHgLRhn",
  "1nYg1Ac4xsGBkmTvhXDzG2",
  "5A9mGMMsmySIZmBH6icc4B",
  "01Oi7A4u4knAEPqylXM9s8",
  "6H3kDe7CGoWYBabAeVWGiD",
  "35q1B8x7zRsITx6SxcWK67",
  "5CIe9u7lex3fxPmwWqrjo3",
  "7rBMZvgeWnOTHWUh3Pvw51",
  "0wZurfElW3yOHscb38vBL8",
  "0m1DJ5Jkv3kdnGrcZsJFmC",
  "5pK4elvBpzeAk8amFG3NVN",
  "0whFZ2qMsiUMkQOxsfRy5p",
  "78sUOio7Q63zyraK2auLla",
  "0BqQWfhMrkpRAUCbdfdHUC",
  "4dT3qLUU6fFUmomLzk2cUA",
  "5ynO8cYFjDwELIZfFHHeYe",
  "2fUesvrGtDQ37bUz30nMak",
  "1rmtygBvOF8Wb1OwVMAyaE",
  "0P2vAvvWni2tNXOdbH3JFk",
  "0xeBC6N81ZBYDtxuBFGSuO",
  "750wm5pwuAQfnSLX8mxa5f",
  "6QewNVIDKdSl8Y3ycuHIei",
  "3aKhLm5mONfAtS1NZXG8f4",
  "2lp0PO2D90zcFWy8toVqgn",
  "0hSUqAj87s0gHUS8U4TRIF",
  "1dfHpGeaXunLRNvzSZOZtc",
  "4E5xVW505akJX0wcKj8Mpd",
  "60QLLec3yKDwloXCyummPy",
  "4EchqUKQ3qAQuRNKmeIpnf",
  "43G3McVkRa8V7oGQzfQuRr",
  "3lSrLqwpS23lMqhtDierCq",
  "1h2xVEoJORqrg71HocgqXd",
  "2SIVPuWP84mPNhF0Ns9nWC",
  "6zsk6uF3MxfIeHPlubKBvR",
  "31er9IGsfFbwqy1pH4aiTP",
  "2NVpYQqdraEcQwqT7GhUkh",
  "0bJKesHl9raebAYBpQp3wv",
  "0L7zm6afBEtrNKo6C6Gj08",
  "6QyBIZEvs11K9lKjyLYtv6",
  "5CeL9C3bsoe4yzYS1Qz8cw",
  "07p7PALHp6ZcD5tmlbO94N",
  "41eFwwTvEhuBgE4SAXxRGd",
  "69MwNXryg6NT1lV7buN7U7",
  "0wZYfxL16dtfTvxFpWTB7L",
  "2IKd8ozOHYuVqrYJ0tqghP",
  "50fGkq9l9Zsn1x7C8GKIYr",
  "0uppYCG86ajpV2hSR3dJJ0",
  "6dmiV9JGjv4vGgLwEZTaOI",
  "4v2rkl1mC3zVAz0nXMx9r4",
  "2TVutF2Xy9R6PLVQ5jEEUs",
  "4KxhIoBjdvaIGA5U6a1c3o",
  "0LtsuNRz3IMRrHCYO9fKRk",
  "4jQDaI7FRGaDB0llURpnNf",
  "0z8oPUM05RZBJ1A1dXPsSs",
  "3CIOopLwvyMvXk97ZEksKO",
  "4xVXe1VS5zlQyECVk6GRrL",
  "54bm2e3tk8cliUz3VSdCPZ",
  "154gL4Xb5AsreMkcDlVFYS",
  "1672RT45nXNUb28fzzPxn8",
  "1a19jsjG2DvbN1fVJonKUU",
  "3fkPMWQ6cBNBLuFcPyMS8s",
  "4E0P1xs3JNmsNr5c5nFTZJ",
  "6CxQsBfTmhx0RsoJoV8hH7",
  "3agtg0x11wPvLIWkYR39nZ",
  "5UWwZ5lm5PKu6eKsHAGxOk",
  "6J5kc12BW5HuP3d7C3vvx8",
  "27BgDmciSjoxTG0almHTpZ",
  "0N3W5peJUQtI4eyR6GJT5O",
  "4fjWStUaP7aXdT0d3YxvPo",
  "2gdtLnVGGg80Kj9GiqP0vH",
  "06h9kk12VjJ2bqcBc6IScR",
  "5sFDReWLrZHLFZFjHsjUTS",
  "5fKZJHzJ9d3MADArbm9muW",
  "0bt3YJTupDqdTKpnFFgs7f",
  "6cr6UDpkjEaMQ80OjWqEBQ",
  "7k0UY4Kabh7SUHXowyfKj7",
  "2amzrvbxYiq8AxGntIiw5V",
  "20KSB3DRekMDCb31rY0ATd",
  "3gjHnylel3PTRpjS44ocqr",
  "7DD7eSuYSC5xk2ArU62esN",
  "5b1jZ9geGD4boxz24XgGPp",
  "033N3Mf87ODmORg6YO61cm",
  "7fcfNW0XxTWlwVlftzfDOR",
  "2id8E4WvczfKHB4LHI7Np3",
  "7qj6lBOB1QTgBmKedXuIbs",
  "2PpNgmrS9mAyrkRAwn6YPq",
  "1CM1wOqD2AIjt2MWd31LV2",
  "2V4Bc2I962j7acQj1N0PiQ",
  "2QSUyofqpGDCo026OPiTBQ",
  "53DfWyh0C0rJUGpsmtdRc1",
  "3YuaBvuZqcwN3CEAyyoaei",
  "5EicljVZKVOo2LZHREtWmQ",
  "0xaNdYwK8ZF3cHSjraQGC0",
  "3QZ7uX97s82HFYSmQUAN1D",
  "4pzcMiIkEv8cOe5vD7xfGq",
  "2VGf3YQ6Zfzb6YyDatYAcY",
  "10V8XpuyMoEcSMfM79WDET",
  "0hDQV9X1Da5JrwhK8gu86p",
  "2854fjg3reX87rDKe6Bk73",
  "4C7Ss9bTPOWJMh3rarF1mN",
  "0ObrXLrfrqJUNc8RfmIBHP",
  "0Dw9z44gXhplDh5HCWZIxP",
  "2Bux4j9el8GFOrvAE8dMA3",
  "4VwPsMcRt1HPVKIdcwY9Uj",
  "2AdRSHeYmDGMrgIfiS2w7K",
  "5Cr3dgYZKJrUTJjy2bEaYa",
  "006yvCdaWUS79qp2Ip3Hdl"
]

# ── SPOTIFY OAuth ─────────────────────────────────────────────────────────────

def get_spotify_token():
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    refresh_token = data["refresh_token"]
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
    )
    result = r.json()
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
    while url:
        r = requests.get(url, headers=headers)
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

# ── STATE ─────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    # First run — seed with all known songs so we don't post them
    print(f"  First run — seeding state with {len(INITIAL_KNOWN_IDS)} known songs.")
    initial = {tid: {"thread_id": None, "name": "", "artist": ""} for tid in INITIAL_KNOWN_IDS}
    save_state(initial)
    return initial

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── DISCORD ───────────────────────────────────────────────────────────────────

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

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def check_for_changes():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking playlist...")
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
        print(f"  + New: {name} -- {artist}")
        thread_id = create_forum_post(
            f"{name} -- {artist}",
            f"🎵 **{name}**\n👤 **Artist:** {artist}\n📅 **Added:** {today}\n🔗 {url}"
        )
        time.sleep(2)
        post_message(UPDATES_CHANNEL_ID, f"✅ **New song added!**\n🎵 {name} -- {artist}\n📅 {today}")
        state[track_id] = {"thread_id": thread_id, "name": name, "artist": artist}
        time.sleep(2)

    for track_id in removed:
        s          = state[track_id]
        name       = s.get("name", track_id)
        artist     = s.get("artist", "")
        thread_id  = s.get("thread_id")
        removed_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")
        print(f"  - Removed: {name} -- {artist}")
        if thread_id:
            post_thread_message(thread_id, f"⚠️ **This song was removed from the playlist.**\n📅 Removed: {removed_at}")
            time.sleep(2)
        post_message(UPDATES_CHANNEL_ID, f"❌ **Song removed.**\n🎵 {name} -- {artist}\n📅 Removed: {removed_at}")
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
