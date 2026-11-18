"""Scheduled, isolated private review; never promotes clips to posting stock.

The owner's decision removes per-BV administrative registration for review
preparation only. It does not establish third-party rights. Catalog metadata
and ordinary access do not prove a license; actual use remains subject to
applicable rights and service terms. All publication receipts stay unverified.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from packages.kyousuki_sources import BVID, EXTRAS, FULL_EP, load_registry, normalize

FOLDER_NAME = "kirinuki-kyousuki-review-private"
FOLDER_TYPE = "application/vnd.google-apps.folder"


def select_review(plan, reg=None, now=None):
    """Only a fresh, account-bound catalog row, never a SERP hint or an approval."""
    reg = reg or load_registry()
    now = now or datetime.now(timezone.utc)
    pool = plan.get("bilibiliSourcePool") or {}
    if pool.get("status") != "ok" or pool.get("discoveryMode") != "public_catalog":
        return None
    if plan.get("shouldProcess") or not plan.get("blockingReasons"):
        return None
    try:
        checked = datetime.fromisoformat(pool["checkedAt"].replace("Z", "+00:00"))
        if not 0 <= (now - checked).total_seconds() <= 6 * 3600:
            return None
        row = pool["latestCatalogCandidate"]
        account = next(a for a in reg["accounts"] if a.get("mid") and
                       str(a["mid"]) == str(row["mid"]) and a["name"] == row["author"])
        posted = datetime.fromisoformat(row["publishedAt"].replace("Z", "+00:00"))
        title = row["title"]
        if (row.get("metadataProvider") != "uapipro"
                or row.get("identityStatus") != "catalog_account_binding"
                or not isinstance(title, str) or not FULL_EP.search(title)
                or EXTRAS.search(title) or not re.search(r"今天喜欢上你了|今天喜欢你了|今喜|今日好き", title)
                or not BVID.fullmatch(str(row["bvid"]))):
            return None
        normalized = normalize({"bvid":row["bvid"], "title":title, "author":account["name"],
            "mid":str(account["mid"]), "duration":row["durationSeconds"],
            "pubdate":int(posted.timestamp())}, account, now)
        if not normalized:
            return None
        return {key:normalized[key] for key in ("bvid","title","author","mid","publishedAt","durationSeconds","episodeKey")}
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, OverflowError):
        return None


def _private_folder(service, folder, primary):
    if not folder or folder == primary or not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValueError("Review destination must be independent of posting stock")
    item = service.files().get(fileId=folder,
        fields="id,name,mimeType,trashed,ownedByMe,driveId,parents", supportsAllDrives=True).execute()
    root = service.files().get(fileId="root", fields="id").execute()["id"]
    if (item.get("name") != FOLDER_NAME or item.get("mimeType") != FOLDER_TYPE
            or item.get("trashed") or item.get("ownedByMe") is not True
            or item.get("driveId") or item.get("parents") != [root]):
        raise ValueError("Review destination must be an owner-only folder at private Drive root")
    page = None
    while True:
        response = service.permissions().list(fileId=folder, pageSize=100,
            pageToken=page, fields="nextPageToken,permissions(type,role)",
            supportsAllDrives=True).execute()
        permissions = response.get("permissions", [])
        if not permissions or any(p.get("type") != "user" or p.get("role") != "owner" for p in permissions):
            raise ValueError("Review destination is shared or permission state is unknown")
        page = response.get("nextPageToken")
        if not page:
            break
    return folder


def ensure_private_folder(service, primary):
    if not primary:
        raise ValueError("Posting stock identity is required for separation")
    response = service.files().list(
        q=f"'root' in parents and name = '{FOLDER_NAME}' and mimeType = '{FOLDER_TYPE}' and trashed = false",
        spaces="drive", fields="nextPageToken,files(id)", pageSize=100).execute()
    items = response.get("files", [])
    if response.get("nextPageToken") or len(items) > 1:
        raise ValueError("Ambiguous private review destination")
    if items:
        folder = items[0]["id"]
    else:
        folder = service.files().create(body={"name":FOLDER_NAME, "mimeType":FOLDER_TYPE,
            "parents":["root"]}, fields="id").execute()["id"]
    return _private_folder(service, folder, primary)


def validate_review_context(bvid, verify_folder=True):
    plan_path = os.environ.get("KYOUSUKI_REVIEW_PLAN")
    if not plan_path:
        raise ValueError("Catalog review requires a fresh plan")
    with Path(plan_path).open("rb") as fh:
        raw = fh.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Review plan exceeds limit")
    candidate = select_review(json.loads(raw))
    if not candidate or candidate["bvid"] != bvid:
        raise ValueError("Source is not the current account-bound review candidate")
    folder = os.environ.get("BILIBILI_REVIEW_FOLDER_ID")
    primary = os.environ.get("KYOUSUKI_PRIMARY_FOLDER_ID")
    if not primary or folder != os.environ.get("GDRIVE_PARENT_FOLDER_ID") or not folder or folder == primary:
        raise ValueError("Private review requires separate Drive destination")
    if verify_folder:
        from packages.shared.gdrive import get_drive_service
        _private_folder(get_drive_service(), folder, primary)
    return candidate


def run_review(path):
    from packages.shared.gdrive import get_drive_service
    from youtube_watcher import load_state_from_drive, load_processed_videos, record_processed_entry
    plan = json.loads(path.read_text(encoding="utf-8"))
    candidate = select_review(plan)
    if not candidate:
        raise RuntimeError("No current catalog review candidate")
    primary = os.environ["GDRIVE_PARENT_FOLDER_ID"]
    service = get_drive_service()
    folder = ensure_private_folder(service, primary)
    sid = f'bilibili_{candidate["bvid"]}_p1_auto'
    entries, file_id = load_processed_videos(service, folder)
    episode = candidate.get("episodeKey")
    state, _ = load_state_from_drive(service, folder, sid)
    if (state.get("status") == "completed" or int(state.get("uploadedClips") or 0)>0
            or any(e.get("status") == "completed" and
                   (e.get("videoId") == sid or (episode and e.get("episodeKey") == episode)) for e in entries)):
        print("PRIVATE_REVIEW_ALREADY_PREPARED", sid)
        return
    prior = next((e for e in entries if e.get("videoId")==sid), {})
    if prior.get("status") == "failed" and int(prior.get("attempts") or 0)>=3:
        raise RuntimeError("Private review exhausted its three attempts")
    os.environ.update(KYOUSUKI_REVIEW_PLAN=str(path.resolve()), KYOUSUKI_PRIMARY_FOLDER_ID=primary,
        GDRIVE_PARENT_FOLDER_ID=folder, BILIBILI_REVIEW_FOLDER_ID=folder, KIRINUKI_TARGET_CLIPS="1",
        SOURCE_VIDEO_TITLE=candidate["title"], SOURCE_VIDEO_PUBLISHED_AT=candidate["publishedAt"])
    cmd = [sys.executable,"run_all.py",candidate["bvid"],"--source-platform","bilibili",
        "--bilibili-page","1","--bilibili-subtitle-lang","auto","--bilibili-catalog-review",
        "--subs","--concept-file","configs/video_concept_kyousuki.md"]
    result = subprocess.run(cmd, check=False, timeout=19_200)
    state, _ = load_state_from_drive(service, folder, sid)
    count = int(state.get("uploadedClips") or 0)
    status = "completed" if result.returncode == 0 and state.get("status")=="completed" and count==1 else "failed"
    record_processed_entry(service, folder, entries, file_id, sid, candidate["title"], status,
        metadata={"episodeKey":episode,"uploadedClips":count,"reviewOnly":True})
    print("PRIVATE_REVIEW_RESULT",json.dumps({"status":status,"bvid":candidate["bvid"],"clips":count,
        "permissionVerified":False,"publicPublishingAuthorized":False,"reviewOnly":True}),flush=True)
    if status!="completed":
        raise RuntimeError("Exactly one completed private review clip was not verified")


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("plan",type=Path)
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    if args.check_only:
        candidate=select_review(json.loads(args.plan.read_text(encoding="utf-8")))
        print("true" if candidate else "false")
    else:
        run_review(args.plan)
