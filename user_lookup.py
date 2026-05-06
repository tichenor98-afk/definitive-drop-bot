"""
user_lookup.py
Fetches the Spotify ID -> Display Name mapping from a public Google Sheet.
Refreshes the cache periodically so new users show up without redeploying.
"""

import csv
import io
import logging
import time
import requests

log = logging.getLogger("users")

CACHE_TTL = 3600  # refresh user list every hour


class UserLookup:
    def __init__(self, sheet_csv_url):
        self.sheet_csv_url = sheet_csv_url
        self._cache        = {}
        self._cache_time   = 0

    def _fetch(self):
        """Fetch the Google Sheet as CSV and parse it."""
        try:
            r = requests.get(self.sheet_csv_url, timeout=10)
            r.raise_for_status()
            reader = csv.DictReader(io.StringIO(r.text))
            new_cache = {}
            for row in reader:
                spotify_id   = row.get("Spotify ID", "").strip()
                display_name = row.get("Display Name", "").strip()
                if spotify_id and display_name:
                    new_cache[spotify_id] = display_name
            log.info(f"User lookup refreshed: {len(new_cache)} users loaded.")
            for uid, name in new_cache.items():
                log.info(f"  {uid} -> {name}")
            return new_cache
        except Exception as e:
            log.warning(f"Failed to fetch user lookup sheet: {e}")
            return None

    def _ensure_cache(self):
        """Ensure the cache is populated and fresh."""
        now = time.time()
        if now - self._cache_time > CACHE_TTL or not self._cache:
            new_cache = self._fetch()
            if new_cache is not None:
                self._cache      = new_cache
                self._cache_time = now
            elif not self._cache:
                log.warning("User lookup cache is empty and fetch failed.")

    def get_name(self, spotify_id):
        """
        Look up a Spotify user ID and return their display name.
        Returns the display name, or the raw ID if not found.
        Always ensures cache is populated before lookup.
        """
        if not spotify_id:
            return "Unknown"

        self._ensure_cache()

        # Clean the ID (remove spotify:user: prefix if present)
        clean_id = spotify_id.replace("spotify:user:", "").strip()
        name = self._cache.get(clean_id)

        if name:
            return name

        log.warning(f"User ID not found in lookup: '{clean_id}'")
        return clean_id

    def is_unknown(self, spotify_id):
        """
        Returns True if this user ID is not in the lookup table.
        Always ensures cache is populated before checking.
        """
        if not spotify_id:
            return True

        self._ensure_cache()

        clean_id = spotify_id.replace("spotify:user:", "").strip()
        return clean_id not in self._cache
