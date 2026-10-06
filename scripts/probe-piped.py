import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/piped.mp4")
output.parent.mkdir(parents=True, exist_ok=True)

# Current official Piped instance list, CDN instances first.
instances = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.nosebs.ru",
    "https://pipedapi-libre.kavin.rocks",
    "https://piped-api.privacy.com.de",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://pipedapi.ducks.party",
    "https://piped-api.codespace.cz",
    "https://pipedapi.reallyaweso.me",
    "https://api.piped.private.coffee",
    "https://pipedapi.darkness.services",
    "https://pipedapi.orangenet.cc",
]

def get_bytes(url, path):
    with requests.get(url, stream=True, timeout=180, headers={"User-Agent": "Mozilla/5.0"}) as r:
        print("stream_status=", r.status_code)
        print("stream_host=", urlparse(r.url).hostname)
        print("stream_type=", r.headers.get("content-type"))
        if r.status_code != 200:
            raise RuntimeError(f"stream HTTP {r.status_code}")
        with path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
    print("stream_bytes=", path.stat().st_size)

errors = []
for base in instances:
    print("instance=", base)
    try:
        r = requests.get(f"{base}/streams/{video_id}", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        print("api_status=", r.status_code)
        if r.status_code != 200:
            errors.append(f"{base}: api {r.status_code}")
            continue
        data = r.json()
        if data.get("error"):
            errors.append(f"{base}: {data.get('error')}")
            continue
        videos = [x for x in (data.get("videoStreams") or []) if x.get("url")]
        audios = [x for x in (data.get("audioStreams") or []) if x.get("url")]
        print("video_streams=", len(videos), "audio_streams=", len(audios))
        print("proxy_url=", data.get("proxyUrl"))
        if not videos:
            errors.append(f"{base}: no video streams")
            continue

        muxed = [x for x in videos if not x.get("videoOnly", True)]
        if muxed:
            chosen = max(muxed, key=lambda x: min(int(x.get("height") or 0), 1080))
            print("mode=muxed quality=", chosen.get("quality"), "videoOnly=", chosen.get("videoOnly"))
            get_bytes(chosen["url"], output)
        else:
            video = max(videos, key=lambda x: min(int(x.get("height") or 0), 1080))
            if not audios:
                errors.append(f"{base}: video-only streams but no audio streams")
                continue
            audio = max(audios, key=lambda x: int(x.get("bitrate") or 0))
            print("mode=merge video_quality=", video.get("quality"), "audio_quality=", audio.get("quality"))
            vp = output.parent / "piped-video.part"
            ap = output.parent / "piped-audio.part"
            get_bytes(video["url"], vp)
            get_bytes(audio["url"], ap)
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(vp), "-i", str(ap), "-c", "copy", str(output)],
                check=True,
                timeout=120,
            )

        size = output.stat().st_size if output.exists() else 0
        print("output_bytes=", size)
        if size > 0:
            print("successful_instance=", base)
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        msg = f"{base}: {type(exc).__name__}: {exc}"
        errors.append(msg)
        print("instance_error=", msg)
        if output.exists():
            output.unlink()

print("errors=", " | ".join(errors))
raise SystemExit(1)
