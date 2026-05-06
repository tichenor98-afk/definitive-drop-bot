"""
state_manager.py
Handles reading, writing, validating, and backing up the bot's state file.
The state tracks which songs are known and their Discord thread IDs.
"""

import hashlib
import json
import logging
import os
import shutil
import time

log = logging.getLogger("state")

STATE_FILE   = "runtime_state.json"
BACKUP_FILES = ["runtime_state.bak1.json", "runtime_state.bak2.json", "runtime_state.bak3.json"]


class StateError(Exception):
    pass


def _checksum(data):
    """Generate a checksum of the state data for corruption detection."""
    serialized = json.dumps(data, sort_keys=True)
    return hashlib.md5(serialized.encode()).hexdigest()


def load_state():
    """
    Load the state file. Returns the state dict, or None if this is a first run.
    Raises StateError if the file exists but is corrupted or empty.
    """
    if not os.path.exists(STATE_FILE):
        log.info("No state file found. This is a first run.")
        return None

    try:
        with open(STATE_FILE) as f:
            raw = f.read().strip()

        if not raw:
            raise StateError("State file exists but is empty.")

        data = json.loads(raw)

        if not isinstance(data, dict):
            raise StateError(f"State file has unexpected format: {type(data)}")

        if len(data) == 0:
            raise StateError("State file exists but contains 0 songs. This is suspicious.")

        log.info(f"State loaded: {len(data)} songs.")
        return data

    except json.JSONDecodeError as e:
        raise StateError(f"State file is corrupted (JSON error): {e}")


def save_state(state):
    """
    Save state to file with backup rotation.
    Keeps 3 rolling backups.
    """
    if not isinstance(state, dict):
        raise StateError(f"Cannot save state: expected dict, got {type(state)}")

    # Rotate backups: bak2 -> bak3, bak1 -> bak2, current -> bak1
    for i in range(len(BACKUP_FILES) - 1, 0, -1):
        if os.path.exists(BACKUP_FILES[i - 1]):
            shutil.copy2(BACKUP_FILES[i - 1], BACKUP_FILES[i])

    if os.path.exists(STATE_FILE):
        shutil.copy2(STATE_FILE, BACKUP_FILES[0])

    # Write new state
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    log.info(f"State saved: {len(state)} songs.")


def load_backup_state():
    """
    Try to load the most recent valid backup.
    Returns the state dict or None if no valid backup exists.
    """
    for backup_file in BACKUP_FILES:
        if not os.path.exists(backup_file):
            continue
        try:
            with open(backup_file) as f:
                data = json.load(f)
            if isinstance(data, dict) and len(data) > 0:
                log.info(f"Loaded backup state from {backup_file}: {len(data)} songs.")
                return data
        except Exception as e:
            log.warning(f"Backup {backup_file} failed to load: {e}")
    return None


def initialize_state(known_ids, spotify_tracks):
    """
    Build the initial state on first run.
    known_ids: set of track IDs we already know about (from CSV)
    spotify_tracks: dict of track_id -> track info from Spotify

    All tracks currently on Spotify are added to state.
    known_ids get thread_id=None (existing posts we can't link to).
    """
    state = {}
    for track_id, track in spotify_tracks.items():
        state[track_id] = {
            "thread_id": None,  # existing songs don't have mapped thread IDs
            "name":      track["name"],
            "artist":    track["artist"],
        }
    log.info(f"State initialized with {len(state)} songs ({len(known_ids)} were pre-existing).")
    return state


def validate_state(state, spotify_track_count):
    """
    Validate state before acting on it.
    Returns (is_valid, reason_if_invalid).
    """
    if not isinstance(state, dict):
        return False, "State is not a dictionary."

    if len(state) == 0:
        return False, "State is empty."

    # If Spotify returned a reasonable number of tracks,
    # make sure state isn't wildly out of sync
    if spotify_track_count > 0:
        ratio = len(state) / spotify_track_count
        if ratio < 0.5 or ratio > 2.0:
            return False, (
                f"State has {len(state)} songs but Spotify has {spotify_track_count}. "
                f"This looks suspicious."
            )

    return True, None
