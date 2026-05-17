"""
leaderboard.py

Builds and posts the Drop Cred leaderboard to Discord.
Maintains a pinned post updated daily and a weekly announcement every Sunday at 3pm UTC.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

from scoring import load_scores, BADGES, get_badge

log = logging.getLogger("leaderboard")

LEADERBOARD_MSG_FILE = "leaderboard_message_id.json"
WEEKLY_POSTED_FILE   = "weekly_posted.json"

DROP_CRED_CHANNEL_ID = "1505592556908449967"

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _headers(bot_token):
    return {
        "Authorization": f"Bot {bot_token}",
        "Content-Type":  "application/json",
    }


def _post_message(bot_token, channel_id, content, retries=3):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    for attempt in range(retries):
        try:
            r = requests.post(url, json={"content": content}, headers=_headers(bot_token), timeout=10)
            if r.status_code in (200, 201):
                return r.json().get("id")
            elif r.status_code == 429:
                wait = float(r.json().get("retry_after", 5))
                time.sleep(wait + 0.5)
                continue
            else:
                log.error(f"Post message failed: {r.status_code} {r.text[:100]}")
                time.sleep(2 ** attempt)
        except requests.RequestException as e:
            log.warning(f"Network error: {e}")
            time.sleep(2 ** attempt)
    return None


def _edit_message(bot_token, channel_id, message_id, content, retries=3):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    for attempt in range(retries):
        try:
            r = requests.patch(url, json={"content": content}, headers=_headers(bot_token), timeout=10)
            if r.status_code == 200:
                return True
            elif r.status_code == 429:
                wait = float(r.json().get("retry_after", 5))
                time.sleep(wait + 0.5)
                continue
            elif r.status_code == 404:
                log.warning("Leaderboard message not found — will create a new one.")
                return False
            else:
                log.error(f"Edit message failed: {r.status_code} {r.text[:100]}")
                time.sleep(2 ** attempt)
        except requests.RequestException as e:
            log.warning(f"Network error: {e}")
            time.sleep(2 ** attempt)
    return False


def _pin_message(bot_token, channel_id, message_id):
    url = f"https://discord.com/api/v10/channels/{channel_id}/pins/{message_id}"
    try:
        r = requests.put(url, headers=_headers(bot_token), timeout=10)
        return r.status_code == 204
    except Exception as e:
        log.warning(f"Could not pin message: {e}")
        return False


def _load_leaderboard_msg_id():
    if os.path.exists(LEADERBOARD_MSG_FILE):
        try:
            with open(LEADERBOARD_MSG_FILE) as f:
                return json.load(f).get("message_id")
        except Exception:
            pass
    return None


def _save_leaderboard_msg_id(msg_id):
    with open(LEADERBOARD_MSG_FILE, "w") as f:
        json.dump({"message_id": msg_id}, f)


def _load_weekly_posted():
    if os.path.exists(WEEKLY_POSTED_FILE):
        try:
            with open(WEEKLY_POSTED_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_posted_week": None}


def _save_weekly_posted(data):
    with open(WEEKLY_POSTED_FILE, "w") as f:
        json.dump(data, f)


def _current_week_key():
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]}"


def build_leaderboard_text(scores):
    """Build the full leaderboard text for the pinned post."""
    now = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    if not scores:
        return f"🏆 **THE DEFINITIVE DROP — DROP CRED**\n_No scores yet. Start adding songs!_\n\nUpdated: {now}"

    # Sort by total score
    ranked = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)

    lines = [
        "🏆 **THE DEFINITIVE DROP — DROP CRED**",
        f"_Updated: {now}_",
        "",
        "**ALL TIME STANDINGS**",
    ]

    for i, (name, data) in enumerate(ranked, 1):
        medal  = MEDALS.get(i, f"{i}.")
        badge  = data.get("badge", get_badge(data["total"]))
        weekly = data.get("weekly", 0)
        weekly_str = f"  _(+{weekly} this week)_" if weekly > 0 else ""
        lines.append(f"{medal} {badge} **{name}** — {data['total']} pts{weekly_str}")

    lines.append("")
    lines.append("*React, comment, add songs and challenge to earn Drop Cred!*")

    return "\n".join(lines)


def build_weekly_announcement(scores):
    """Build the weekly recap announcement."""
    now = datetime.now(timezone.utc).strftime("%B %d, %Y")

    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)
    weekly_ranked = sorted(scores.items(), key=lambda x: x[1].get("weekly", 0), reverse=True)

    # Top overall
    top_overall = ranked[0][0] if ranked else None
    # Biggest mover this week
    top_weekly = next((name for name, data in weekly_ranked if data.get("weekly", 0) > 0), None)

    lines = [
        f"🎵 **WEEKLY DROP CRED RECAP — {now}**",
        "",
    ]

    if top_overall:
        lines.append(f"👑 **Overall leader:** {top_overall} — {ranked[0][1]['total']} pts")

    if top_weekly and top_weekly != top_overall:
        weekly_pts = scores[top_weekly].get("weekly", 0)
        lines.append(f"🔥 **Biggest mover this week:** {top_weekly} (+{weekly_pts} pts)")

    lines.append("")
    lines.append("**THIS WEEK'S LEADERBOARD**")

    for i, (name, data) in enumerate(weekly_ranked[:5], 1):
        weekly = data.get("weekly", 0)
        if weekly == 0:
            break
        medal = MEDALS.get(i, f"{i}.")
        lines.append(f"{medal} **{name}** — +{weekly} pts this week")

    lines.append("")
    lines.append("_Keep adding songs, commenting, and challenging to climb the ranks!_")

    return "\n".join(lines)


def update_pinned_leaderboard(bot_token, scores):
    """Update or create the pinned leaderboard post in #Drop Cred."""
    content    = build_leaderboard_text(scores)
    msg_id     = _load_leaderboard_msg_id()

    if msg_id:
        success = _edit_message(bot_token, DROP_CRED_CHANNEL_ID, msg_id, content)
        if success:
            log.info("Leaderboard updated.")
            return
        # Message was deleted — create a new one
        msg_id = None

    # Create new pinned post
    new_msg_id = _post_message(bot_token, DROP_CRED_CHANNEL_ID, content)
    if new_msg_id:
        _pin_message(bot_token, DROP_CRED_CHANNEL_ID, new_msg_id)
        _save_leaderboard_msg_id(new_msg_id)
        log.info(f"Leaderboard created and pinned. Message ID: {new_msg_id}")


def post_weekly_announcement(bot_token, scores):
    """Post the weekly recap if it's Sunday at 3pm UTC and not already posted this week."""
    now         = datetime.now(timezone.utc)
    week_key    = _current_week_key()
    posted_data = _load_weekly_posted()

    # Check if it's Sunday (weekday 6) and between 15:00-15:10 UTC
    if now.weekday() != 6:
        return False
    if not (15 <= now.hour < 16):
        return False
    if posted_data.get("last_posted_week") == week_key:
        return False

    content = build_weekly_announcement(scores)
    if not content:
        return False

    msg_id = _post_message(bot_token, DROP_CRED_CHANNEL_ID, content)
    if msg_id:
        posted_data["last_posted_week"] = week_key
        _save_weekly_posted(posted_data)
        log.info("Weekly announcement posted.")
        return True

    return False
