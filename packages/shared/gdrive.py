import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload


SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRET_PATH = Path("client_secret.json")
TOKEN_PATH = Path("gdrive_token.json")


def sanitize_filename(name: str) -> str:
    """Remove characters unsupported by most filesystems."""
    if not isinstance(name, str):
        name = str(name or "")
    sanitized = re.sub(r'[<>:"/\\|?*]', "", name)
    sanitized = re.sub(r"[\r\n\t]+", " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "clip"


def build_safe_filename(base: str, suffix: str, max_bytes: int = 240) -> str:
    """
    Combine base and suffix ensuring the resulting filename stays within byte limits.
    ext4/NTFS allow 255 bytes; leave headroom for safety.
    """
    base = (base or "").strip() or "clip"
    suffix = (suffix or "").strip()

    candidate = f"{base}{suffix}"
    if len(candidate.encode("utf-8")) <= max_bytes:
        return candidate

    encoded_suffix = suffix.encode("utf-8")
    budget = max_bytes - len(encoded_suffix)
    truncated = []
    consumed = 0
    for ch in base:
        ch_bytes = ch.encode("utf-8")
        if consumed + len(ch_bytes) > budget:
            break
        truncated.append(ch)
        consumed += len(ch_bytes)

    safe_base = "".join(truncated).rstrip() or "clip"
    return f"{safe_base}{suffix}"


def _prepare_token_from_env() -> None:
    """Bootstrap credential files from environment variables if they are missing."""
    if CLIENT_SECRET_PATH.exists() and TOKEN_PATH.exists():
        return

    secret_payload = os.environ.get("GDRIVE_CLIENT_SECRET_JSON")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")
    if not secret_payload or not refresh_token:
        raise RuntimeError(
            "Google Drive credentials are missing. "
            "Set GDRIVE_CLIENT_SECRET_JSON and GDRIVE_REFRESH_TOKEN or run authenticate_gdrive.py."
        )

    try:
        client_secret_data = json.loads(secret_payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid GDRIVE_CLIENT_SECRET_JSON payload: {exc}") from exc

    CLIENT_SECRET_PATH.write_text(json.dumps(client_secret_data), encoding="utf-8")

    client_info = client_secret_data.get("web") or client_secret_data.get("installed")
    if not client_info:
        raise RuntimeError("Client secret JSON must contain a 'web' or 'installed' key.")

    token_payload = {
        "token": None,
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_info["client_id"],
        "client_secret": client_info["client_secret"],
        "scopes": SCOPES,
    }
    TOKEN_PATH.write_text(json.dumps(token_payload), encoding="utf-8")


def get_gdrive_credentials() -> Credentials:
    """Return Google Drive credentials, refreshing them when necessary."""
    _prepare_token_from_env()

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Google Drive credentials are invalid. "
                "Run authenticate_gdrive.py or ensure refresh token is set."
            )
    return creds


def get_drive_service():
    """Build and return a Google Drive API service client."""
    creds = get_gdrive_credentials()
    return build("drive", "v3", credentials=creds)


def upload_file(
    service,
    local_path: Path,
    remote_name: str,
    parent_folder_id: str,
    resumable_threshold_bytes: int = 5 * 1024 * 1024,
) -> Optional[str]:
    """
    Upload a file to Google Drive, returning the file ID on success.
    Uses resumable upload for files above the threshold.
    """
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    file_metadata = {"name": remote_name, "parents": [parent_folder_id]}
    media = MediaFileUpload(str(local_path), resumable=local_path.stat().st_size > resumable_threshold_bytes)

    try:
        request = service.files().create(body=file_metadata, media_body=media, fields="id")
        if media.resumable:
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"  -> Upload progress: {int(status.progress() * 100)}% ({remote_name})")
        else:
            response = request.execute()
        file_id = response.get("id") if isinstance(response, dict) else None
        if file_id:
            print(f"  -> Uploaded to Drive: {remote_name} (id={file_id})")
        return file_id
    except HttpError as exc:
        print(f"  -> Google Drive upload failed for {remote_name}: {exc}", file=sys.stderr)
        raise


def find_file(service, parent_id: str, name: str) -> Optional[dict]:
    """Finds a file by name within the specified parent folder."""
    query = (
        f"'{parent_id}' in parents and name = '{name}' "
        "and trashed = false"
    )
    response = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name, mimeType)",
        pageSize=1,
    ).execute()
    files = response.get("files", [])
    return files[0] if files else None


def download_file_bytes(service, file_id: str) -> bytes:
    """Downloads the contents of a file as bytes."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()


def upload_json_data(service, parent_id: str, name: str, payload: bytes, file_id: Optional[str] = None) -> str:
    """Uploads or updates a JSON file."""
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json", resumable=False)
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    metadata = {
        "name": name,
        "parents": [parent_id],
        "mimeType": "application/json",
    }
    response = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return response["id"]
