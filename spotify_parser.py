"""
spotify_parser.py

Parses raw Spotify API responses into clean, normalized track data.
Designed to be resilient to Spotify API structure changes.

Key design principles:
- Discovers track data by content (has id + name + artists), not by key name
- Logs the structure it finds on every run
- Alerts when structure changes from last known good
- Never silently returns 0 tracks — treats it as an error
- Tries multiple field name variants before giving up
- Fully isolated from bot logic so it can be updated independently
"""

import hashlib
import json
import logging
import os

log = logging.getLogger("parser")

# File that stores the last known good structure signature
# If the structure changes, the bot will alert you
STRUCTURE_CACHE_FILE = "last_known_structure.json"

# Field name variants to try, in priority order.
# If Spotify renames a field, add the new name at the front.
FIELD_VARIANTS = {
    "id":       ["id", "track_id", "spotifyId", "spotify_id"],
    "name":     ["name", "title", "trackName", "track_name"],
    "artists":  ["artists", "performers", "artistList", "artist_list"],
    "ext_urls": ["external_urls", "externalUrls", "urls"],
    "album":    ["album", "albumInfo", "release"],
}


def _get_field(obj, field_key):
    """Try all known variants of a field name."""
    for variant in FIELD_VARIANTS.get(field_key, [field_key]):
        val = obj.get(variant)
        if val is not None:
            return val
    return None


def _find_track_data(item):
    """
    Recursively search an item for a dict that looks like track data.
    A track dict is identified by having: id, name, and artists.
    Returns (track_dict, key_path) or (None, None).
    
    This approach means we don't care what key Spotify uses —
    we find the track by its content, not its location.
    """
    if not item or not isinstance(item, dict):
        return None, None

    # Check all values at the top level first
    for key, value in item.items():
        if not isinstance(value, dict):
            continue
        # Does this dict look like a track?
        has_id      = bool(_get_field(value, "id"))
        has_name    = bool(_get_field(value, "name"))
        has_artists = bool(_get_field(value, "artists"))
        if has_id and has_name and has_artists:
            return value, key

    # If not found at top level, search one level deeper
    for key, value in item.items():
        if not isinstance(value, dict):
            continue
        for sub_key, sub_value in value.items():
            if not isinstance(sub_value, dict):
                continue
            has_id      = bool(_get_field(sub_value, "id"))
            has_name    = bool(_get_field(sub_value, "name"))
            has_artists = bool(_get_field(sub_value, "artists"))
            if has_id and has_name and has_artists:
                return sub_value, f"{key}.{sub_key}"

    return None, None


def _get_structure_signature(item):
    """
    Build a hashable signature of an item's structure.
    Used to detect when Spotify changes their response format.
    """
    if not item:
        return "null"

    def get_keys_recursive(obj, depth=0):
        if depth > 3 or not isinstance(obj, dict):
            return {}
        return {
            k: get_keys_recursive(v, depth + 1)
            for k, v in obj.items()
            if not isinstance(v, list)  # skip lists for simplicity
        }

    structure = get_keys_recursive(item)
    serialized = json.dumps(structure, sort_keys=True)
    return hashlib.md5(serialized.encode()).hexdigest()


def _load_known_structure():
    """Load the last known good structure from disk."""
    if os.path.exists(STRUCTURE_CACHE_FILE):
        try:
            with open(STRUCTURE_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_known_structure(signature, track_key, sample_keys):
    """Save the current structure as the known good structure."""
    try:
        with open(STRUCTURE_CACHE_FILE, "w") as f:
            json.dump({
                "signature":   signature,
                "track_key":   track_key,
                "sample_keys": sample_keys,
            }, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save structure cache: {e}")


def parse_playlist_items(items):
    """
    Parse a list of raw Spotify playlist items into normalized track dicts.
    
    Returns:
        tracks: dict of track_id -> track info
        warnings: list of warning messages (empty if all good)
        structure_changed: True if Spotify's format changed since last run
    
    Never returns an empty dict without raising — if we got items but
    parsed 0 tracks, that's an error condition, not a valid result.
    """
    if not items:
        return {}, ["No items provided to parser"], False

    tracks = {}
    warnings = []
    skipped = 0
    structure_changed = False

    # Check structure of first valid item
    first_item = next((i for i in items if i), None)
    if first_item:
        current_sig = _get_structure_signature(first_item)
        known = _load_known_structure()

        if known is None:
            # First run — save this as the known good structure
            track_data, track_key = _find_track_data(first_item)
            sample_keys = list(track_data.keys())[:10] if track_data else []
            _save_known_structure(current_sig, track_key, sample_keys)
            log.info(f"Structure saved. Track data found at: item['{track_key}']")
            log.info(f"Track fields available: {sample_keys}")
        elif known["signature"] != current_sig:
            # Structure has changed since last run
            structure_changed = True
            track_data, track_key = _find_track_data(first_item)
            msg = (
                f"Spotify API structure has changed! "
                f"Track data previously at item['{known['track_key']}'], "
                f"now at item['{track_key}']. "
                f"Parser has adapted automatically."
            )
            warnings.append(msg)
            log.warning(msg)
            # Update the saved structure
            sample_keys = list(track_data.keys())[:10] if track_data else []
            _save_known_structure(current_sig, track_key, sample_keys)
        else:
            log.info(f"Structure matches last known good. Track data at: item['{known['track_key']}']")

    # Parse all items
    for i, item in enumerate(items):
        if not item:
            skipped += 1
            continue

        track, track_key = _find_track_data(item)

        if not track:
            log.warning(f"Item {i+1}: Could not find track data. Top-level keys: {list(item.keys())}")
            skipped += 1
            continue

        # Skip episodes/podcasts
        track_type = track.get("type", "")
        is_episode = track.get("episode", False)
        if track_type == "episode" or is_episode is True:
            log.debug(f"Item {i+1}: Skipping episode.")
            skipped += 1
            continue

        # Extract track ID
        track_id = _get_field(track, "id")
        if not track_id:
            log.warning(f"Item {i+1}: Track has no ID. Skipping.")
            skipped += 1
            continue

        # Extract name
        name = _get_field(track, "name") or "Unknown Title"

        # Extract artists
        artists_data = _get_field(track, "artists") or []
        if isinstance(artists_data, list):
            artist = ", ".join(
                a.get("name", "") for a in artists_data
                if isinstance(a, dict) and a.get("name")
            )
        else:
            artist = "Unknown Artist"
        if not artist:
            artist = "Unknown Artist"

        # Extract Spotify URL
        ext_urls = _get_field(track, "ext_urls") or {}
        if isinstance(ext_urls, dict):
            url = ext_urls.get("spotify") or f"https://open.spotify.com/track/{track_id}"
        else:
            url = f"https://open.spotify.com/track/{track_id}"

        # Extract album art
        album_art = ""
        album = track.get("album") or {}
        if isinstance(album, dict):
            images = album.get("images", [])
            if images and isinstance(images, list):
                album_art = images[0].get("url", "")

        # Extract added_by from outer item
        added_by_id = ""
        added_by = item.get("added_by")
        if isinstance(added_by, dict):
            added_by_id = added_by.get("id", "")

        added_at = item.get("added_at", "")

        tracks[track_id] = {
            "id":        track_id,
            "name":      name,
            "artist":    artist,
            "url":       url,
            "album_art": album_art,
            "added_by":  added_by_id,
            "added_at":  added_at,
        }

    log.info(f"Parsed {len(tracks)} tracks, skipped {skipped} items.")

    # Critical check: if we got items but parsed 0 tracks, something is wrong
    if len(items) > 0 and len(tracks) == 0:
        raise ValueError(
            f"Parser received {len(items)} items but produced 0 tracks. "
            f"This is a parsing failure, not an empty playlist. "
            f"Check warnings above for details on what was received."
        )

    return tracks, warnings, structure_changed
