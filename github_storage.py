"""
github_storage.py

Persists bot state files to GitHub so they survive Railway redeployments.
Uses the GitHub Contents API to read/write files directly to the repo.

Files persisted:
  - drop_cred_scores.json    (scores for all users)
  - drop_cred_scanned.json   (what messages have been scored)
  - playlist_state.json      (known Spotify tracks)

How it works:
  On startup: pull latest files from GitHub
  After each scan: push updated files back to GitHub
"""

import base64
import json
import logging
import os
import time

import requests

log = logging.getLogger("github")

GITHUB_API = "https://api.github.com"


class GitHubStorage:
    def __init__(self, token, repo, branch="main"):
        """
        token:  GitHub personal access token with repo write access
        repo:   e.g. "tichenor98-afk/definitive-drop-bot"
        branch: usually "main"
        """
        self.token  = token
        self.repo   = repo
        self.branch = branch
        self.headers = {
            "Authorization": f"token {token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
        }

    def _url(self, path):
        return f"{GITHUB_API}/repos/{self.repo}/contents/{path}"

    def read(self, path):
        """Read a file from GitHub. Returns (content_str, sha) or (None, None)."""
        r = requests.get(self._url(path), headers=self.headers, timeout=10)
        if r.status_code == 404:
            return None, None
        if r.status_code != 200:
            log.warning(f"GitHub read failed for {path}: {r.status_code}")
            return None, None
        data    = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha     = data["sha"]
        return content, sha

    def write(self, path, content_str, message="Bot state update"):
        """Write a file to GitHub. Creates or updates as needed."""
        _, sha = self.read(path)
        encoded = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": encoded,
            "branch":  self.branch,
        }
        if sha:
            payload["sha"] = sha

        for attempt in range(3):
            r = requests.put(
                self._url(path),
                json=payload,
                headers=self.headers,
                timeout=15,
            )
            if r.status_code in (200, 201):
                log.info(f"GitHub: saved {path}")
                return True
            elif r.status_code == 409:
                # Conflict — re-fetch SHA and retry
                log.warning(f"GitHub conflict on {path}, retrying...")
                _, sha = self.read(path)
                if sha:
                    payload["sha"] = sha
                time.sleep(2)
            else:
                log.warning(f"GitHub write failed for {path}: {r.status_code} {r.text[:100]}")
                time.sleep(2 ** attempt)
        return False

    def pull_file(self, path, local_path):
        """Download a file from GitHub to local disk."""
        content, _ = self.read(path)
        if content is None:
            log.info(f"GitHub: {path} not found (new file)")
            return False
        try:
            with open(local_path, "w") as f:
                f.write(content)
            log.info(f"GitHub: pulled {path} -> {local_path}")
            return True
        except Exception as e:
            log.warning(f"Could not write {local_path}: {e}")
            return False

    def push_file(self, local_path, remote_path, message="Bot state update"):
        """Upload a local file to GitHub."""
        try:
            with open(local_path) as f:
                content = f.read()
            return self.write(remote_path, content, message)
        except FileNotFoundError:
            log.warning(f"Local file not found: {local_path}")
            return False
        except Exception as e:
            log.warning(f"Could not read {local_path}: {e}")
            return False


def setup_storage():
    """Create GitHubStorage from environment variables. Returns None if not configured."""
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPO", "tichenor98-afk/definitive-drop-bot")
    if not token:
        log.warning(
            "GITHUB_TOKEN not set. State will not persist across redeployments. "
            "Set GITHUB_TOKEN in Railway variables to enable persistence."
        )
        return None
    return GitHubStorage(token, repo)
