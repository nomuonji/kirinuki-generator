"""Small durable per-lane JSON journal on a dedicated GitHub branch.

A failed journal write stops publishing. The journal holds no video bytes or OAuth
tokens. Use one GitHub Actions concurrency group per destination lane.
"""
from __future__ import annotations
import base64
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote
import requests


class GitHubLedger:
    def __init__(self, lane: str, *, token=None, repository=None, branch="kirinuki-state"):
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY")
        self.branch = branch
        self.path = f"lanes/{lane}.json"
        if not self.token or not self.repository or "/" not in self.repository:
            raise RuntimeError("GitHub ledger requires GITHUB_TOKEN and GITHUB_REPOSITORY")
        self.sha = None
        self.data = {"version": 1, "lane": lane, "sources": {}, "clips": {}}

    def _call(self, method, route, *, payload=None, allow=None):
        response = requests.request(
            method,
            f"https://api.github.com/repos/{self.repository}/{route}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            json=payload, timeout=25,
        )
        if response.status_code not in (allow or (200, 201)):
            raise RuntimeError(f"GitHub journal API {method} failed with HTTP {response.status_code}: {response.text[:350]}")
        return response.json() if response.content else {}

    def _ensure_branch(self):
        route = f"git/ref/heads/{quote(self.branch, safe='')}"
        response = requests.get(
            f"https://api.github.com/repos/{self.repository}/{route}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            timeout=25,
        )
        if response.status_code == 200:
            return
        if response.status_code != 404:
            raise RuntimeError(f"Cannot inspect journal branch: HTTP {response.status_code}")
        main = self._call("GET", "git/ref/heads/main")
        self._call("POST", "git/refs", payload={
            "ref": f"refs/heads/{self.branch}", "sha": main["object"]["sha"]
        })

    def load(self):
        self._ensure_branch()
        route = f"contents/{self.path}?ref={quote(self.branch, safe='')}"
        response = requests.get(
            f"https://api.github.com/repos/{self.repository}/{route}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            timeout=25,
        )
        if response.status_code == 404:
            self.sha = None
            return self.data
        if response.status_code != 200:
            raise RuntimeError(f"Cannot load publishing journal: HTTP {response.status_code}")
        body = response.json()
        self.sha = body["sha"]
        decoded = json.loads(base64.b64decode(body["content"]).decode("utf-8"))
        if (decoded.get("version") != 1 or decoded.get("lane") != self.data["lane"]
                or not isinstance(decoded.get("sources"), dict)
                or not isinstance(decoded.get("clips"), dict)):
            raise RuntimeError("Invalid GitHub journal; refusing to overwrite or publish")
        self.data = decoded
        return self.data

    def save(self):
        self.data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        payload = {
            "message": f"journal: {self.data['lane']} publishing state",
            "branch": self.branch,
            "content": base64.b64encode(
                json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            ).decode("ascii"),
        }
        if self.sha:
            payload["sha"] = self.sha
        result = self._call("PUT", f"contents/{self.path}", payload=payload)
        self.sha = result["content"]["sha"]

    def clip(self, key):
        return self.data["clips"].get(key)

    def set_clip(self, key, **fields):
        value = self.data["clips"].setdefault(key, {})
        value.update(fields)
        self.save()
        return value

    def set_source(self, source_id, **fields):
        value = self.data["sources"].setdefault(source_id, {})
        value.update(fields)
        self.save()
        return value
