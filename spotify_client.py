"""
spotify_client.py
Handles all Spotify API interaction with robust error handling,
token refresh, retry logic, and structural change detection.
"""

import json
import logging
import time
import requests

log = logging.getLogger("spotify")

# Minimum fraction of previously known tracks that must be returned
# before we trust the response. Protects against partial/bad responses.
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
                raise SpotifyError("spotify_token.json exists but has no refresh_token field.")
            return token
        except FileNotFoundError:
            raise SpotifyError(f"Token file '{self.token_file}' not found. Run get_spotify_token.py.")
        except json.JSONDecodeError:
            raise SpotifyError(f"Token file '{self.token_file}' is corrupted.")

    def _save_refresh_token(self, new_token):
        try:
            with open(self.token_file, "w") as f:
                json.dump({"refresh_token": new_token}, f)
        except Exception as e:
            log.warning(f"Could not save new refresh token: {e}")

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
                        f"Spotify token refresh failed (400). "
                        f"The refresh token may have expired. Run get_spotify_token.py to fix."
                    )
                else:
                    log.warning(f"Token refresh attempt {attempt+1} failed: {r.status_code}")
                    time.sleep(2 ** attempt)
            except requests.RequestException as e:
                log.warning(f"Token refresh attempt {attempt+1} network error: {e}")
                time.sleep(2 ** attempt)
        raise SpotifyError("Failed to refresh Spotify token after 3 attempts.")

    # ── API requests ──────────────────────────────────────────────────────────

    def _get(self, url, retries=3):
        """Make a GET request with retry logic and token refresh on 401."""
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
                    log.info("Access token expired, refreshing...")
                    self.access_token = None
                    self.refresh_access_token()
                    continue
                elif r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 5))
                    log.warning(f"Spotify rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after + 1)
                    continue
                elif r.status_code in (500, 502, 503, 504):
                    log.warning(f"Spotify server error {r.status_code}. Attempt {attempt+1}/{retries}.")
                    time.sleep(2 ** attempt)
                    continue
                else:
                    raise SpotifyError(f"Spotify API returned {r.status_code}: {r.text[:200]}")
            except requests.RequestException as e:
                log.warning(f"Network error on attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
        raise SpotifyError(f"Failed to fetch {url} after {retries} attempts.")

    # ── Playlist fetching ─────────────────────────────────────────────────────

    def _parse_item(self, item):
        """
        Safely parse one item from the playlist response.
        Returns a track dict or None if the item should be skipped.
        Handles structural changes defensively.
        """
        if not item:
            return None

        # The /items endpoint wraps tracks under a "track" key
        track = item.get("track")
        if not track:
            log.debug(f"Item has no 'track' key. Keys present: {list(item.keys())}")
            return None

        # Skip episodes (podcasts)
        if track.get("type") == "episode":
            return None

        # Must have an ID
        track_id = track.get("id")
        if not track_id:
            return None

        # Safely extract fields with fallbacks
        name = track.get("name", "Unknown Title")

        artists = track.get("artists", [])
        if artists and isinstance(artists, list):
            artist = ", ".join(
                a.get("name", "") for a in artists if isinstance(a, dict)
            )
        else:
            artist = "Unknown Artist"

        external_urls = track.get("external_urls", {})
        url = external_urls.get("spotify", f"https://open.spotify.com/track/{track_id}")

        # Extract who added this track
        added_by_id = ""
        if isinstance(item.get("added_by"), dict):
            added_by_id = item["added_by"].get("id", "")

        added_at = item.get("added_at", "")

        return {
            "id":         track_id,
            "name":       name,
            "artist":     artist,
            "url":        url,
            "added_by":   added_by_id,
            "added_at":   added_at,
        }

    def get_playlist_tracks(self, previous_count=None):
        """
        Fetch all tracks from the playlist.
        Returns a dict of track_id -> track info.

        Raises SpotifyError if the response looks suspicious
        (too few tracks compared to previous_count).
        """
        tracks = {}
        url    = f"https://api.spotify.com/v1/playlists/{self.playlist_id}/items"
        page   = 1

        while url:
            log.info(f"Fetching playlist page {page}...")
            data = self._get(url)

            items = data.get("items", [])
            log.info(f"Page {page}: {len(items)} items returned.")

            for item in items:
                parsed = self._parse_item(item)
                if parsed:
                    tracks[parsed["id"]] = parsed

            url  = data.get("next")
            page += 1

        log.info(f"Total tracks fetched: {len(tracks)}")

        # Sanity check: if we have a previous count, make sure
        # this response is not suspiciously small
        if previous_count and previous_count > 0:
            fraction = len(tracks) / previous_count
            if fraction < MIN_TRACK_FRACTION:
                raise SpotifyError(
                    f"Suspicious response: got {len(tracks)} tracks but expected "
                    f"~{previous_count}. This may be a bad API response. Skipping."
                )

        return tracks
