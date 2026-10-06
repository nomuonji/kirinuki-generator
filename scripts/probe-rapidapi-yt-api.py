import json
import os
import sys
from pathlib import Path

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/rapidapi.mp4")
key = os.environ.get("RAPIDAPI_KEY")
if not key:
    raise SystemExit("RAPIDAPI_KEY is not configured")

headers = {
    "X-RapidAPI-Key": key,
    "X-RapidAPI-Host": "yt-api.p.rapidapi.com",
}
resp = requests.get(
    "https://yt-api.p.rapidapi.com/dl",
    headers=headers,
    params={"id": video_id},
    timeout=60,
)
print("api_status=", resp.status_code)
if resp.status_code != 200:
    print(resp.text[:1000], file=sys.stderr)
    raise SystemExit(2)

data = resp.json()
print("response_keys=", sorted(data.keys()))
formats = data.get("formats") or []
adaptive = data.get("adaptiveFormats") or []
print("formats=", len(formats), "adaptiveFormats=", len(adaptive))

def summary(f):
    return {
        "itag": f.get("itag"),
        "qualityLabel": f.get("qualityLabel"),
        "height": f.get("height"),
        "mimeType": f.get("mimeType"),
        "hasAudio": f.get("hasAudio"),
        "hasVideo": f.get("hasVideo"),
        "hasUrl": bool(f.get("url")),
    }

for f in formats[:10]:
    print("format=", json.dumps(summary(f), ensure_ascii=False))

candidates = [f for f in formats if f.get("url")]
if not candidates:
    raise SystemExit("YT-API /dl returned no directly downloadable muxed formats")

def score(f):
    h = int(f.get("height") or 0)
    has_audio = f.get("hasAudio")
    if has_audio is None:
        mime = (f.get("mimeType") or "").lower()
        has_audio = "audio" in mime or "mp4" in mime
    return (1 if has_audio else 0, h)

selected = max(candidates, key=score)
print("selected=", json.dumps(summary(selected), ensure_ascii=False))
url = selected["url"]

output.parent.mkdir(parents=True, exist_ok=True)
with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as dl:
    print("download_status=", dl.status_code)
    print("content_type=", dl.headers.get("content-type"))
    dl.raise_for_status()
    with output.open("wb") as fh:
        for chunk in dl.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)

print("downloaded_bytes=", output.stat().st_size)
if output.stat().st_size <= 0:
    raise SystemExit("downloaded file is empty")
