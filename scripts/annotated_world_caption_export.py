"""Private candidate-caption intake for The Annotated World.

Uses the existing kirinuki-generator RapidAPI key. Never prints caption text,
secrets, signed URLs or Google Drive file IDs, and never uploads GitHub artifacts.
Run only in trusted main workflow, not in a pull request.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re

from transcribe_rapidapi import (
    _normalize_segments,
    fetch_transcript_from_rapidapi_1,
    fetch_transcript_from_rapidapi_2,
)
from packages.shared.gdrive import get_drive_service, find_file, upload_json_data

VIDEO_ID = "4YSXNotY8QU"
FOLDER_NAME = "the-annotated-world-private-sources"
CAPTION_FILE = f"{VIDEO_ID}.rapidapi-candidate.json"
METADATA_FILE = f"{VIDEO_ID}.candidate-evidence.json"


def checked_private_folder(service) -> str:
    """Find/create a non-shared folder owned by the existing Drive identity."""
    safe_name = FOLDER_NAME.replace("'", "\\'")
    result = service.files().list(
        q=f"name = '{safe_name}' and mimeType = 'application/vnd.google-apps.folder' and 'root' in parents and trashed = false",
        fields="files(id, name, shared),nextPageToken",
        pageSize=100,
    ).execute()
    matches = result.get("files", [])
    if result.get("nextPageToken"):
        raise RuntimeError("Ambiguous private folder search; refusing export")
    if len(matches) > 1:
        raise RuntimeError("Duplicate private folders; refusing export")
    if matches:
        folder = matches[0]
    else:
        folder = service.files().create(
            body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
            fields="id,shared",
        ).execute()
    if folder.get("shared") is not False:
        # Re-read when Drive did not return the field on create.
        folder = service.files().get(fileId=folder["id"], fields="id,shared").execute()
    if folder.get("shared") is not False:
        raise RuntimeError("Source folder access is not verified private; refusing export")
    return folder["id"]


def main() -> None:
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("Existing RAPIDAPI_KEY secret is unavailable")
    # First successful known provider for this exact video; no new ASR.
    raw = fetch_transcript_from_rapidapi_1(VIDEO_ID, key, "en")
    provider = "rapidapi1"
    if not raw:
        raw = fetch_transcript_from_rapidapi_2(VIDEO_ID, key)
        provider = "rapidapi2"
    if not raw:
        raise RuntimeError("RapidAPI did not return caption candidates")
    segments = _normalize_segments(raw)
    count = len(segments)
    last = max((segment["end"] for segment in segments), default=0)
    if count < 1000 or last < 5600 or last > 6000:
        raise RuntimeError("Source caption coverage is incomplete or mismatched")
    # This checks gross language mix-up, not word-for-word source accuracy.
    all_text = "".join(segment["text"] for segment in segments)
    english_letters = len(re.findall(r"[A-Za-z]", all_text))
    cjk = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", all_text))
    if english_letters < 5000 or cjk > english_letters // 8:
        raise RuntimeError("Candidate captions are not clearly English")
    if any(segments[i]["start"] > segments[i+1]["start"] for i in range(count - 1)):
        raise RuntimeError("Non-monotonic timestamps")
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    source = {
        "videoId": VIDEO_ID,
        "sourceUrl": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "provider": provider,
        "method": "RapidAPI existing-caption candidate (not direct original verified)",
        "languageRequested": "en",
        "capturedAt": captured_at,
        "segments": segments,
    }
    body = json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = sha256(body).hexdigest()
    evidence = {
        "videoId": VIDEO_ID,
        "provider": provider,
        "originVerified": False,
        "languageRequested": "en",
        "capturedAt": captured_at,
        "segmentCount": count,
        "lastCaptionSecond": last,
        "sourceSha256": digest,
        "sourceBytes": len(body),
        "storage": "private Google Drive, no public artifact",
        "publication": "editorial review and quotation/rights gate required",
    }
    service = get_drive_service()
    folder = checked_private_folder(service)
    for name, payload in [
        (CAPTION_FILE, body),
        (METADATA_FILE, json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")),
    ]:
        current = find_file(service, folder, name)
        upload_json_data(service, folder, name, payload, current["id"] if current else None)
    print("RAPIDAPI_CAPTION_INTAKE=SUCCESS")
    print("PROVIDER=" + provider)
    print("SEGMENT_COUNT=" + str(count))
    print("LAST_END_SECONDS=" + str(last))
    print("CAPTION_SHA256=" + digest)
    print("PRIVATE_DRIVE_EXPORT=SUCCESS")
    # Secret and transcript never leave GitHub Secrets/Drive through logs or artifacts.


if __name__ == "__main__":
    main()
