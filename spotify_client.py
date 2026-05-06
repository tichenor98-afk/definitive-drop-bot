"""
spotify_client.py
Handles all Spotify API interaction: authentication, token refresh,
retry logic, and rate limit handling.
Delegates all response parsing to spotify_parser.py.
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
        """Get a fresh access token using the stored refresh token."""
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
                    raise SpotifyError(
                        "Spotify token refresh failed (400 Bad Request). "
                        "The refresh token may have expired. "
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

        Uses spotify_parser.py to parse the response, which handles
        structure discovery and change detection automatically.

        Raises SpotifyError if:
        - The API call fails
        - The response looks suspiciously small compared to previous count
        - The parser receives items but produces 0 tracks
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

        # Sanity check before parsing
        if len(all_items) == 0:
            raise SpotifyError(
                "Spotify returned 0 items for the playlist. "
                "This is unexpected — the playlist should have songs. "
                "This may be a temporary API issue."
            )

        # Parse using the resilient parser
        try:
            tracks, warnings, structure_changed = parse_playlist_items(all_items)
        except ValueError as e:
            raise SpotifyError(str(e))

        # Return warnings and structure change flag alongside tracks
        # so the bot can alert the user
        self._last_warnings        = warnings
        self._last_structure_changed = structure_changed

        # Sanity check: response should not be suspiciously small
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
