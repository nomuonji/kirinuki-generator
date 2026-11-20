"""One-off, explicitly owner-requested public upload of one Kyousuki Drive clip.

Deliberately separate from recurring publication approval state. Does not assert
source permission, edit approval flags, or enable unattended publication. A
durable GitHub journal prevents blind retries after an ambiguous upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from packages.github_ledger import GitHubLedger
from packages.shared.gdrive import (
    download_file_bytes,
    download_file_to_path,
    get_drive_service,
    list_clip_files,
)
from packages.youtube_direct import auth_youtube, fingerprint_of, owned_videos, readback_video
from packages.quality_gate import verify_rendered_media
from scripts.kyousuki_publish import OFFICIAL_CHANNEL, verified_stock_folder

BVID = re.compile(r"BV[A-Za-z0-9]{10}")


def matching_sidecar(drive, folder: str, video: dict) -> dict | None:
    name = video["name"][:-4] + ".json"
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    result = drive.files().list(
        q=f"'{folder}' in parents and name = '{escaped}' and trashed = false",
        fields="nextPageToken,files(id,size,mimeType)", pageSize=2,
    ).execute()
    entries = result.get("files") or []
    if len(entries) != 1 or result.get("nextPageToken"):
        return None
    if int(entries[0].get("size") or 0) > 2_000_000:
        return None
    if entries[0].get("mimeType") != "application/json":
        return None
    try:
        value = json.loads(download_file_bytes(drive, entries[0]["id"]))
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeError):
        return None


def source_bvid(audit: dict) -> str | None:
    value = str(audit.get("sourceContentId") or audit.get("sourceVideoId") or "")
    match = BVID.search(value)
    return match.group(0) if match else None


def choose_stock(drive, folder: str, clips: list, ledger: GitHubLedger, used: set):
    for clip in reversed(clips):
        sidecar = matching_sidecar(drive, folder, clip)
        if not sidecar:
            continue
        audit = sidecar.get("kirinukiAudit") or {}
        bvid = source_bvid(audit)
        if not bvid or audit.get("sourcePlatform") != "bilibili":
            continue
        key = hashlib.sha256(("kyousuki-manual-v1:" + clip["id"]).encode()).hexdigest()[:24]
        if key in ledger.data["clips"] or key in used:
            continue
        raw_title = sidecar.get("title") or sidecar.get("clipTitle") or ""
        raw_title = re.sub(r"[\r\n\t]+", " ", str(raw_title)).strip()
        if not raw_title or len(raw_title) < 6:
            raw_title = "今日、好きになりました。 切り抜き"
        title = raw_title[:95]
        description = (
            "『今日、好きになりました。』に関する非公式の切り抜き動画です。\n"
            "参考にした掲載ページ: https://www.bilibili.com/video/" + bvid + "\n\n"
            "KIRINUKI-ID:" + key + "\n"
            "KIRINUKI-SOURCE:" + bvid
        )
        return clip, key, bvid, title, description
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--upload-public", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.upload_public:
        raise SystemExit("Specify exactly one of --inspect and --upload-public")

    folder = os.getenv("GDRIVE_PARENT_FOLDER_ID", "")
    destination = os.getenv("YOUTUBE_DESTINATION_CHANNEL_ID", "")
    if not folder or not destination or destination == OFFICIAL_CHANNEL:
        raise SystemExit("Destination or Drive folder missing/invalid")
    drive = get_drive_service()
    if not verified_stock_folder(drive, folder):
        raise SystemExit("Drive folder is not the dedicated kyo-suki/short folder")

    youtube, playlist = auth_youtube()
    ledger = GitHubLedger("kyousuki-manual-once")
    ledger.load()
    existing = owned_videos(youtube, playlist, limit=250)
    used = {fingerprint_of(video) for video in existing}
    stock = list_clip_files(drive, folder)
    selected = choose_stock(drive, folder, stock, ledger, used)
    if not selected:
        print("MANUAL_KYOUSUKI_RESULT no_unused_video_with_source_metadata")
        raise SystemExit(1)
    clip, key, bvid, title, description = selected
    print("MANUAL_KYOUSUKI_SELECTED", json.dumps(
        {"key": key, "stockCount": len(stock), "title": title, "sourceId": bvid},
        ensure_ascii=False, sort_keys=True), flush=True)
    if args.inspect:
        print("MANUAL_KYOUSUKI_RESULT inspect_success", flush=True)
        return

    # Record the attempt before network IO: re-running may only reconcile.
    ledger.set_clip(key, status="uploading", attemptedAt=__import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), sourceId=bvid, title=title)
    with tempfile.TemporaryDirectory(prefix="kyousuki-one-") as temp:
        path = Path(temp) / "manual-once.mp4"
        download_file_to_path(drive, clip["id"], path)
        verify_rendered_media(path)
        print("MANUAL_KYOUSUKI_MEDIA_QA", json.dumps({"bytes": path.stat().st_size}),
              flush=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": description,
                    "categoryId": "22",
                    "defaultLanguage": "ja",
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            },
            media_body=MediaFileUpload(
                str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                resumable=True),
        )
        result = None
        try:
            while result is None:
                _, result = request.next_chunk(num_retries=1)
        except Exception as error:
            # A failed transport does not prove YouTube rejected the upload.
            ledger.set_clip(key, status="uncertain", failure=type(error).__name__)
            print("MANUAL_KYOUSUKI_RESULT uncertain_upload_" + type(error).__name__,
                  flush=True)
            raise SystemExit(2) from None
        if not result or not result.get("id"):
            ledger.set_clip(key, status="uncertain", failure="no_video_id")
            raise SystemExit("Upload outcome uncertain: missing video ID")
        video_id = result["id"]
        ledger.set_clip(key, status="verification_pending", videoId=video_id)
        try:
            remote = readback_video(youtube, video_id)
        except Exception as error:
            print("MANUAL_KYOUSUKI_RESULT readback_pending_" + type(error).__name__,
                  flush=True)
            raise SystemExit(3) from None
        if not remote:
            print("MANUAL_KYOUSUKI_RESULT readback_pending_no_video", flush=True)
            raise SystemExit(3)
        actual_channel = (remote.get("snippet") or {}).get("channelId")
        privacy = (remote.get("status") or {}).get("privacyStatus")
        if actual_channel != destination or fingerprint_of(remote) != key:
            print("MANUAL_KYOUSUKI_RESULT mismatched_readback", flush=True)
            raise SystemExit(4)
        state = "published" if privacy == "public" else "uploaded_" + str(privacy)
        ledger.set_clip(key, status=state, videoId=video_id, privacyStatus=privacy)
        if privacy == "public":
            try:
                drive.files().update(
                    fileId=clip["id"],
                    body={"name": "posted_manual_" + key + ".mp4"},
                    fields="id").execute()
            except Exception as error:
                print("MANUAL_KYOUSUKI_STOCK_RENAME_FAILED", type(error).__name__,
                      flush=True)
        print("MANUAL_KYOUSUKI_RESULT", json.dumps(
            {"status": state, "videoId": video_id,
             "privacy": privacy, "channelMatched": True},
            ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
