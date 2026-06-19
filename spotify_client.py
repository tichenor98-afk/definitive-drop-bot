"""
spotify_client.py
Handles all Spotify API interaction: authentication, token refresh,
retry logic, and rate limit handling.
Delegates all response parsing to spotify_parser.py.

Updated June 2026: handles Spotify's new 6-month refresh token expiry policy.
When a refresh token expires (invalid_grant), the bot alerts #bot-alerts
and shuts down gracefully rather than retrying with a dead token.
"""

import json
import logging
import time
import requests

from spotify_parser import parse_playlist_items

log = logging.getLogger("spotify")

# Minimum fraction of previously known tracks that must be returned
# before we trust the response. Protects against partial responses.
MIN_TRACK_FRACTION = 0.80


class SpotifyError(Exception):
    pass


class SpotifyTokenExpiredError(SpotifyError):
    """
    Raised when the refresh token has expired (Spotify invalid_grant).
    This requires human intervention — the bot cannot recover automatically.
    The owner must run get_spotify_token.py to generate a new token.
    """
    pass


class SpotifyClient:
    def __init__(self, client_id, client_secret, playlist_id, token_file):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.playlist_id   = playlist_id
        self.token_file    = token_file
        self.access_token  = None

    # ── Authentication ────────────────────────────────────────────────────────

    def _load_refresh_token(self):
        try:
            with open(self.token_file) as f:
                data = json.load(f)
            token = data.get("refresh_token")
            if not token:
                raise SpotifyError(
                    f"'{self.token_file}' exists but has no refresh_token. "
                    f"Run get_spotify_token.py to generate a new token."
                )
            return token
        except FileNotFoundError:
            raise SpotifyError(
                f"Token file '{self.token_file}' not found. "
                f"Run get_spotify_token.py to generate a token."
            )
        except json.JSONDecodeError:
            raise SpotifyError(
                f"Token file '{self.token_file}' is corrupted. "
                f"Run get_spotify_token.py to regenerate it."
            )

    def _save_refresh_token(self, new_token):
        try:
            with open(self.token_file, "w") as f:
                json.dump({"refresh_token": new_token}, f)
        except Exception as e:
            log.warning(f"Could not save updated refresh token: {e}")

    def refresh_access_token(self):
        """
        Get a fresh access token using the stored refresh token.

        Raises SpotifyTokenExpiredError if Spotify returns invalid_grant,
        which means the refresh token has expired (Spotify's 6-month policy).
        The owner must run get_spotify_token.py to fix this.
        """
        refresh_token = self._load_refresh_token()
        for attempt in range(3):
            try:
                r = requests.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "grant_type":    "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    auth=(self.client_id, self.client_secret),
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()
                    self.access_token = data["access_token"]
                    if "refresh_token" in data:
                        self._save_refresh_token(data["refresh_token"])
                    log.info("Spotify access token refreshed.")
                    return

                elif r.status_code == 400:
                    error_data  = r.json()
                    error_code  = error_data.get("error", "")
                    error_desc  = error_data.get("error_description", "")

                    if error_code == "invalid_grant":
                        # ── Spotify 6-month token expiry ──────────────────
                        # Per Spotify's June 2026 policy, refresh tokens
                        # expire after 6 months. Do NOT retry — discard
                        # the token and require the owner to reauthorize.
                        log.error(
                            "Spotify refresh token has expired (invalid_grant). "
                            "Owner must run get_spotify_token.py to reauthorize."
                        )
                        raise SpotifyTokenExpiredError(
                            "Spotify refresh token expired (invalid_grant).\n"
                            "Action required: run get_spotify_token.py on your computer, "
                            "then upload the new spotify_token.json to GitHub.\n"
                            f"Spotify error: {error_desc}"
                        )
                    else:
                        raise SpotifyError(
                            f"Spotify token refresh failed (400): {error_code} — {error_desc}. "
                            "Run get_spotify_token.py to generate a new token."
                        )

                elif r.status_code == 401:
                    raise SpotifyError(
                        "Spotify token refresh failed (401 Unauthorized). "
                        "Check your SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
                    )
                else:
                    log.warning(
                        f"Token refresh attempt {attempt+1}/3 failed: "
                        f"HTTP {r.status_code}"
                    )
                    time.sleep(2 ** attempt)
            except requests.RequestException as e:
                log.warning(f"Token refresh attempt {attempt+1}/3 network error: {e}")
                time.sleep(2 ** attempt)
        raise SpotifyError("Failed to refresh Spotify token after 3 attempts.")

    # ── API requests ──────────────────────────────────────────────────────────

    def _get(self, url, retries=3):
        """
        Make an authenticated GET request with retry logic.
        Handles token expiry, rate limits, and server errors.
        """
        for attempt in range(retries):
            if not self.access_token:
                self.refresh_access_token()
            try:
                r = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=15,
                )
                if r.status_code == 200:
                    return r.json()

                elif r.status_code == 401:
                    log.info("Access token expired. Refreshing...")
                    self.access_token = None
                    self.refresh_access_token()
                    continue

                elif r.status_code == 403:
                    raise SpotifyError(
                        f"Spotify returned 403 Forbidden for {url}. "
                        f"The OAuth token may not have the required scopes. "
                        f"Run get_spotify_token.py to regenerate the token."
                    )

                elif r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 5))
                    log.warning(f"Spotify rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after + 1)
                    continue

                elif r.status_code in (500, 502, 503, 504):
                    log.warning(
                        f"Spotify server error {r.status_code}. "
                        f"Attempt {attempt+1}/3."
                    )
                    time.sleep(2 ** attempt)
                    continue

                else:
                    raise SpotifyError(
                        f"Spotify API returned unexpected status {r.status_code}. "
                        f"Response: {r.text[:200]}"
                    )

            except requests.RequestException as e:
                log.warning(f"Network error on attempt {attempt+1}/3: {e}")
                time.sleep(2 ** attempt)

        raise SpotifyError(f"Failed to fetch {url} after {retries} attempts.")

    # ── Playlist fetching ─────────────────────────────────────────────────────

    def get_playlist_tracks(self, previous_count=None):
        """
        Fetch all tracks from the playlist.
        Returns a dict of track_id -> track info.
        """
        all_items = []
        url = f"https://api.spotify.com/v1/playlists/{self.playlist_id}/items"
        page = 1

        while url:
            log.info(f"Fetching playlist page {page}...")
            data = self._get(url)

            items = data.get("items", [])
            total = data.get("total", "?")
            log.info(f"Page {page}: {len(items)} items (total in playlist: {total})")

            all_items.extend(items)
            url  = data.get("next")
            page += 1

        log.info(f"Total raw items fetched: {len(all_items)}")

        if len(all_items) == 0:
            raise SpotifyError(
                "Spotify returned 0 items for the playlist. "
                "This is unexpected — the playlist should have songs. "
                "This may be a temporary API issue."
            )

        try:
            tracks, warnings, structure_changed = parse_playlist_items(all_items)
        except ValueError as e:
            raise SpotifyError(str(e))

        self._last_warnings          = warnings
        self._last_structure_changed = structure_changed

        if previous_count and previous_count > 0:
            fraction = len(tracks) / previous_count
            if fraction < MIN_TRACK_FRACTION:
                raise SpotifyError(
                    f"Suspicious response: parsed {len(tracks)} tracks but "
                    f"expected ~{previous_count} (got {fraction:.0%} of expected). "
                    f"This may be a bad API response. Skipping this check."
                )

        log.info(f"Successfully parsed {len(tracks)} tracks.")
        return tracks
