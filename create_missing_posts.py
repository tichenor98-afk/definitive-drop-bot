"""
create_missing_posts.py

Creates Discord forum posts in #the-playlist for songs
that were added to Spotify but missed by the bot.
Run ONCE then delete.
"""

import json
import time
import requests

DISCORD_BOT_TOKEN  = "MTQ5OTg4Nzg3NDU4NDIxOTc3OQ.GRyWno.QoTuR78cOlxGH9LOeqYH_Y7OK6X6hM2cCH9y84"
FORUM_CHANNEL_ID   = "1499885742095208599"
UPDATES_CHANNEL_ID = "1501346456852758669"

HEADERS = {
    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    "Content-Type":  "application/json",
}

MISSING_SONGS = [
    {"name": "Junior Citizen",                    "artist": "Poster Children",          "url": "https://open.spotify.com/track/5A4Fm34uwC5o71CwEyzZ6v"},
    {"name": "Get Up, Stand Up",                  "artist": "Bob Marley & The Wailers", "url": "https://open.spotify.com/track/0q5giEtY4wsFTwjWqswLwx"},
    {"name": "Cold",                              "artist": "Chris Stapleton",          "url": "https://open.spotify.com/track/24nhOvYX2gk3txBbMzXeUB"},
    {"name": "i'm confident that i'm insecure",   "artist": "Lawrence",                 "url": "https://open.spotify.com/track/43WqAFtBHbnYbxzvVJRNEZ"},
    {"name": "Everyday Sunshine",                 "artist": "Fishbone",                 "url": "https://open.spotify.com/track/1QJQwHjaamdmdmoaN47NCD"},
    {"name": "Rosemary",                          "artist": "Lenny Kravitz",            "url": "https://open.spotify.com/track/5bcjFv3wpykUYOLhdVKYt3"},
    {"name": "Down To The Bottom",                "artist": "Dorothy",                  "url": "https://open.spotify.com/track/0Wi3WUcwypMsOQWu70C5z1"},
    {"name": "Lesson Learnt",                     "artist": "Aaron Taylor",             "url": "https://open.spotify.com/track/7hXtZAHYedEOK3pGdWD6iQ"},
    {"name": "Oh, Atlanta",                       "artist": "Alison Krauss",            "url": "https://open.spotify.com/track/2JXtwlRd6FQ4CLeYLj7yJ8"},
    {"name": "broken people",                     "artist": "almost monday",            "url": "https://open.spotify.com/track/0GOffguGbp8RViiVFaPCU2"},
    {"name": "Lose My Cool - Franc Moody Remix",  "artist": "Amber Mark",               "url": "https://open.spotify.com/track/4gdQamULpFs7WeyFGfmTCZ"},
    {"name": "Little Plastic Castle",             "artist": "Ani DiFranco",             "url": "https://open.spotify.com/track/1XAY4zlJWqJl3d6Eqy1A7q"},
    {"name": "Colors",                            "artist": "Black Pumas",              "url": "https://open.spotify.com/track/6d4FWjx72iuRWzn1HwywLK"},
    {"name": "Cowboy",                            "artist": "Asher cataldo",            "url": "https://open.spotify.com/track/4Q5mUPPX8sxZIstOIxPOyA"},
    {"name": "The Real Thing",                    "artist": "Audra Mae",                "url": "https://open.spotify.com/track/1j0S5iV8KPvBnUIRzzhGYr"},
    {"name": "Slipping Away",                     "artist": "Autumn Reverie",           "url": "https://open.spotify.com/track/25DCPSFRM2JenVmSuyjk2A"},
]

ADDED_BY = "Jeremy Jones"
ADDED_AT = "May 19, 2026"

def create_forum_post(song):
    title   = f"{song['name']} — {song['artist']}"
    content = (
        f"🎵 **{song['name']}**\n"
        f"Artist: {song['artist']}\n"
        f"Added by: {ADDED_BY}\n"
        f"Added: {ADDED_AT}\n"
        f"{song['url']}"
    )
    for attempt in range(3):
        r = requests.post(
            f"https://discord.com/api/v10/channels/{FORUM_CHANNEL_ID}/threads",
            json={"name": title, "message": {"content": content}},
            headers=HEADERS,
        )
        if r.status_code in (200, 201):
            thread_id = r.json().get("id")
            print(f"  Created: {title} (thread {thread_id})")
            return thread_id
        elif r.status_code == 429:
            wait = r.json().get("retry_after", 5)
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(float(wait) + 1)
        else:
            print(f"  FAILED ({r.status_code}): {r.text[:100]}")
            return None
    return None

def post_to_updates(song):
    content = (
        f"✅ **Song Added**\n"
        f"Track: {song['name']}\n"
        f"Artist: {song['artist']}\n"
        f"Added by: {ADDED_BY}\n"
        f"Added: {ADDED_AT}"
    )
    r = requests.post(
        f"https://discord.com/api/v10/channels/{UPDATES_CHANNEL_ID}/messages",
        json={"content": content},
        headers=HEADERS,
    )
    if r.status_code in (200, 201):
        print(f"  Logged in #playlist-updates")
    else:
        print(f"  Failed to log: {r.status_code}")

def main():
    print(f"Creating {len(MISSING_SONGS)} missing Discord posts...\n")
    created = 0
    for i, song in enumerate(MISSING_SONGS, 1):
        print(f"[{i}/{len(MISSING_SONGS)}] {song['name']} — {song['artist']}")
        thread_id = create_forum_post(song)
        if thread_id:
            created += 1
            time.sleep(1)
            post_to_updates(song)
        time.sleep(2)
    print(f"\nDone. Created {created}/{len(MISSING_SONGS)} posts.")

if __name__ == "__main__":
    main()
