import json
import os
import sys
from pathlib import Path

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/yt-api-cgeo.mp4")
key = os.environ["RAPIDAPI_KEY"]

api = requests.get(
    "https://yt-api.p.rapidapi.com/dl",
    params={"id": video_id, "cgeo": "US", "geo": "US", "lang": "en"},
    headers={
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": "yt-api.p.rapidapi.com",
        "User-Agent": "Mozilla/5.0",
    },
    timeout=60,
)
print("api_status=", api.status_code)
print("api_server=", api.headers.get("server"))
api.raise_for_status()
data = api.json()
print("status=", data.get("status"))
print("title=", data.get("title"))
print("isProxied=", data.get("isProxied"))
print("pmReg=", data.get("pmReg"))

formats = [f for f in (data.get("formats") or []) if f.get("url")]
print("format_count=", len(formats))
for f in formats[:10]:
    print("format=", json.dumps({
        "itag": f.get("itag"),
        "height": f.get("height"),
        "qualityLabel": f.get("qualityLabel"),
        "mimeType": f.get("mimeType"),
        "url_host": requests.utils.urlparse(f.get("url")).hostname,
    }, ensure_ascii=False))

if not formats:
    raise SystemExit("no muxed direct formats")

selected = max(formats, key=lambda f: int(f.get("height") or 0))
url = selected["url"]
print("selected_itag=", selected.get("itag"), "height=", selected.get("height"))

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Referer": "https://www.youtube.com/",
    "Origin": "https://www.youtube.com",
}
output.parent.mkdir(parents=True, exist_ok=True)
with requests.get(url, headers=headers, stream=True, timeout=180, allow_redirects=True) as r:
    print("download_status=", r.status_code)
    print("content_type=", r.headers.get("content-type"))
    print("content_length=", r.headers.get("content-length"))
    if r.status_code >= 400:
        print(r.text[:500], file=sys.stderr)
    r.raise_for_status()
    with output.open("wb") as fh:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                fh.write(chunk)

print("downloaded_bytes=", output.stat().st_size)
