import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/cobalt.mp4")
api = "http://127.0.0.1:9000"

info = requests.get(api + "/", timeout=30)
print("cobalt_info_status=", info.status_code)
info.raise_for_status()
meta = info.json()
print("cobalt_version=", (meta.get("cobalt") or {}).get("version"))
print("youtube_supported=", "youtube" in ((meta.get("cobalt") or {}).get("services") or []))

payload = {
    "url": f"https://www.youtube.com/watch?v={video_id}",
    "videoQuality": "360",
    "youtubeVideoCodec": "h264",
    "youtubeVideoContainer": "mp4",
    "alwaysProxy": True,
}
resp = requests.post(
    api + "/",
    json=payload,
    headers={"Accept": "application/json", "Content-Type": "application/json"},
    timeout=90,
)
print("cobalt_request_status=", resp.status_code)
try:
    data = resp.json()
except Exception:
    print(resp.text[:1500], file=sys.stderr)
    raise
print("cobalt_response=", json.dumps({
    "status": data.get("status"),
    "filename": data.get("filename"),
    "error": data.get("error"),
    "has_url": bool(data.get("url")),
}, ensure_ascii=False))

if resp.status_code != 200 or data.get("status") == "error":
    raise SystemExit(2)

url = data.get("url")
if not url:
    raise SystemExit(f"Cobalt returned no downloadable URL: {data.get('status')}")

parsed = urlparse(url)
print("download_host=", parsed.hostname)
print("download_path=", parsed.path)

output.parent.mkdir(parents=True, exist_ok=True)
with requests.get(url, stream=True, timeout=180, headers={"User-Agent": "Mozilla/5.0"}) as dl:
    print("download_status=", dl.status_code)
    print("content_type=", dl.headers.get("content-type"))
    print("content_length=", dl.headers.get("content-length"))
    dl.raise_for_status()
    with output.open("wb") as fh:
        for chunk in dl.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)

size = output.stat().st_size
print("downloaded_bytes=", size)
if size <= 0:
    raise SystemExit("Cobalt returned an empty file")
