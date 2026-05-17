"""
discord_client.py
Handles all Discord API interaction with retry logic,
rate limit handling, and post verification.
"""

import logging
import time
import requests

log = logging.getLogger("discord")

DISCORD_API = "https://discord.com/api/v10"


class DiscordError(Exception):
    pass


class DiscordClient:
    def __init__(self, bot_token, forum_channel_id, updates_channel_id, alerts_channel_id):
        self.bot_token          = bot_token
        self.forum_channel_id   = forum_channel_id
        self.updates_channel_id = updates_channel_id
        self.alerts_channel_id  = alerts_channel_id

    @property
    def _headers(self):
        return {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type":  "application/json",
        }

    # ── Core request ──────────────────────────────────────────────────────────

    def _post(self, url, payload, retries=3, verify=True):
        """
        POST to Discord with retry logic and rate limit handling.
        Returns the response JSON on success, raises DiscordError on failure.
        """
        for attempt in range(retries):
            try:
                r = requests.post(url, json=payload, headers=self._headers, timeout=10)

                if r.status_code in (200, 201):
                    return r.json()

                elif r.status_code == 429:
                    retry_after = r.json().get("retry_after", 5)
                    log.warning(f"Discord rate limited. Waiting {retry_after}s...")
                    time.sleep(float(retry_after) + 0.5)
                    continue

                elif r.status_code == 401:
                    raise DiscordError(
                        "Discord returned 401 Unauthorized. "
                        "The bot token may be invalid or expired."
                    )

                elif r.status_code == 403:
                    raise DiscordError(
                        f"Discord returned 403 Forbidden for {url}. "
                        "Check bot permissions."
                    )

                elif r.status_code in (500, 502, 503, 504):
                    log.warning(f"Discord server error {r.status_code}. Attempt {attempt+1}/{retries}.")
                    time.sleep(2 ** attempt)
                    continue

                else:
                    log.warning(f"Discord returned {r.status_code}: {r.text[:200]}. Attempt {attempt+1}/{retries}.")
                    time.sleep(2 ** attempt)
                    continue

            except requests.RequestException as e:
                log.warning(f"Discord network error attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)

        raise DiscordError(f"Failed to POST to Discord after {retries} attempts.")

    def _verify_message_exists(self, channel_id, message_id):
        """Verify a message was actually posted by fetching it back."""
        try:
            r = requests.get(
                f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}",
                headers=self._headers,
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Public actions ────────────────────────────────────────────────────────

    def test_connection(self):
        """
        Verify the bot token is valid by fetching the bot's own user info.
        Returns True if connected, raises DiscordError if not.
        """
        try:
            r = requests.get(
                f"{DISCORD_API}/users/@me",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 200:
                username = r.json().get("username", "unknown")
                log.info(f"Discord connected as: {username}")
                return True
            elif r.status_code == 401:
                raise DiscordError(
                    "Discord bot token is invalid. Reset the token in the "
                    "Discord developer portal and update DISCORD_BOT_TOKEN."
                )
            else:
                raise DiscordError(f"Discord connection test failed: {r.status_code}")
        except requests.RequestException as e:
            raise DiscordError(f"Discord connection test network error: {e}")

    def create_forum_post(self, title, content):
        """
        Create a new post in the forum channel.
        Returns the thread ID on success, raises DiscordError on failure.
        """
        log.info(f"Creating forum post: {title}")
        result = self._post(
            f"{DISCORD_API}/channels/{self.forum_channel_id}/threads",
            {"name": title, "message": {"content": content}},
        )
        thread_id = result.get("id")
        if not thread_id:
            raise DiscordError(f"Forum post created but no thread ID returned: {result}")
        log.info(f"Forum post created. Thread ID: {thread_id}")
        return thread_id

    def post_to_updates(self, content):
        """Post a message to #playlist-updates."""
        log.info(f"Posting to #playlist-updates: {content[:80]}...")
        result = self._post(
            f"{DISCORD_API}/channels/{self.updates_channel_id}/messages",
            {"content": content},
        )
        msg_id = result.get("id")
        if msg_id and not self._verify_message_exists(self.updates_channel_id, msg_id):
            log.warning("Could not verify #playlist-updates message was posted.")
        return msg_id

    def post_message(self, channel_id, message):
        """Post a message to any channel by ID."""
        return self._post_message(channel_id, message)

    def post_to_alerts(self, content):
        """Post a message to #bot-alerts (private, owner only)."""
        log.info(f"Posting to #bot-alerts: {content[:80]}...")
        try:
            self._post(
                f"{DISCORD_API}/channels/{self.alerts_channel_id}/messages",
                {"content": content},
            )
        except DiscordError as e:
            # Don't let alert failures crash the bot
            log.error(f"Failed to post to #bot-alerts: {e}")

    def comment_on_post(self, thread_id, content):
        """
        Post a comment inside an existing forum thread.
        Returns True on success, False if thread not found.
        """
        if not thread_id:
            return False
        log.info(f"Commenting on thread {thread_id}: {content[:60]}...")
        try:
            self._post(
                f"{DISCORD_API}/channels/{thread_id}/messages",
                {"content": content},
            )
            return True
        except DiscordError as e:
            log.warning(f"Could not comment on thread {thread_id}: {e}")
            return False
