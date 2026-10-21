"""YouTube OAuth upload and readback. This module never enables a channel."""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from packages.publish_scheduler import marker, utc_now

class UploadDeferred(RuntimeError):
    """Provider confirms an upload was rejected before success."""

class UploadUncertain(RuntimeError):
    """Transport/response unknown: reconcile YouTube before any retry."""


def auth_youtube():
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
                "YOUTUBE_DESTINATION_CHANNEL_ID")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"YouTube OAuth is unavailable: {', '.join(missing)}")
    credentials = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    client = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    me = client.channels().list(part="id,contentDetails", mine=True).execute()
    ids = [ch["id"] for ch in me.get("items", [])]
    expected = os.environ["YOUTUBE_DESTINATION_CHANNEL_ID"].strip()
    if expected not in ids:
        raise RuntimeError("OAuth channel does not match YOUTUBE_DESTINATION_CHANNEL_ID; no uploading permitted")
    entry = next(ch for ch in me["items"] if ch["id"] == expected)
    playlist = entry["contentDetails"]["relatedPlaylists"]["uploads"]
    return client, playlist


def owned_videos(client, uploads_playlist: str, limit=250):
    """Read actual private/scheduled uploads for dedupe and slot reconciliation."""
    found = []
    page_token = None
    while len(found) < limit:
        response = client.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist,
            maxResults=min(50, limit-len(found)), pageToken=page_token,
        ).execute()
        ids = [v["contentDetails"].get("videoId") for v in response.get("items", [])]
        ids = [v for v in ids if v]
        if ids:
            actual = client.videos().list(part="id,snippet,status", id=",".join(ids)).execute()
            found.extend(actual.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token or not ids:
            break
    return found


def source_of(video: dict) -> str | None:
    text = (video.get("snippet") or {}).get("description") or ""
    match = re.search(r"KIRINUKI-SOURCE:([A-Za-z0-9_-]{11})", text)
    return match.group(1) if match else None


def fingerprint_of(video: dict) -> str | None:
    text = (video.get("snippet") or {}).get("description") or ""
    match = re.search(r"KIRINUKI-ID:([a-f0-9]{24})", text)
    return match.group(1) if match else None


def reservations(videos: list[dict]) -> list[dict]:
    result = []
    for v in videos:
        status = v.get("status") or {}
        future = status.get("publishAt")
        if future and status.get("privacyStatus") == "private":
            result.append({"publishAt": future, "sourceVideoId": source_of(v),
                           "videoId": v.get("id")})
    return result


def upload_once(client, file_path: Path, *, title: str, description: str,
                source_video_id: str, fingerprint: str, publish_at: str):
    """Submit one resumable YouTube upload with initial scheduling.

    All nonexplicitly-rejected failures are considered uncertain. In that case
    do not call this method again until list-your-uploads reconciliation.
    """
    if not file_path.is_file():
        raise RuntimeError("Cannot upload missing MP4")
    body = {
        "snippet": {
            "title": str(title).replace("**", "")[:98],
            "description": (
                str(description)[:3800] + "\n\n"
                + f"元動画: https://www.youtube.com/watch?v={source_video_id}\n"
                + f"KIRINUKI-SOURCE:{source_video_id}\n"
                + marker(fingerprint)
            )[:4900],
            "categoryId": "22",
            "defaultLanguage": "ja",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }
    request = client.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(file_path), mimetype="video/mp4",
                                   chunksize=8*1024*1024, resumable=True),
    )
    result = None
    try:
        while result is None:
            _, result = request.next_chunk(num_retries=1)
        if not result or not result.get("id"):
            raise UploadUncertain("Video insert completed without a video ID")
    except HttpError as exc:
        reason = ""
        try:
            details = json.loads(exc.content.decode("utf-8"))
            errors = details.get("error", {}).get("errors", [])
            reason = ",".join(x.get("reason", "") for x in errors)
        except (ValueError, AttributeError, UnicodeDecodeError):
            reason = ""
        definite = ("uploadLimitExceeded", "quotaExceeded", "dailyLimitExceeded",
                    "rateLimitExceeded", "userRateLimitExceeded", "uploadLimitExceeded")
        if exc.resp.status in (400, 403) and any(k in reason for k in definite):
            raise UploadDeferred(f"YouTube upload rejected: {reason}") from exc
        raise UploadUncertain(f"YouTube upload outcome unknown: HTTP {exc.resp.status}, {reason}") from exc
    except UploadUncertain:
        raise
    except Exception as exc:
        raise UploadUncertain(f"YouTube upload outcome unknown: {type(exc).__name__}") from exc

    video_id = result["id"]
    # Fetching a newly inserted video can be eventually consistent. The ID is
    # committed by the caller immediately, even if readback has not converged.
    return {"videoId": video_id, "publishAt": publish_at,
            "uploadedAt": utc_now().isoformat(),
            "privacyStatus": result.get("status", {}).get("privacyStatus", "")}


def readback_video(client, video_id: str) -> dict | None:
    response = client.videos().list(part="id,snippet,status", id=video_id).execute()
    items = response.get("items", [])
    return items[0] if items else None
