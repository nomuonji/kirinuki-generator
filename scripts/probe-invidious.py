import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/invidious.mp4")
output.parent.mkdir(parents=True, exist_ok=True)

# Current public instances listed by the official Invidious documentation.
# Try the JP instance first because the production workload includes Japanese videos.
instances = [
    "https://invidious.f5.si",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yt.chocolatemoo53.com",
    "https://invidious.tiekoetter.com",
]

errors = []
for base in instances:
    print("instance=", base)
    try:
        api = f"{base}/api/v1/videos/{video_id}?local=true&region=JP"
        r = requests.get(api, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        print("api_status=", r.status_code)
        if r.status_code != 200:
            errors.append(f"{base}: api {r.status_code}")
            continue
        data = r.json()
        streams = data.get("formatStreams") or []
        print("format_streams=", len(streams))
        candidates = []
        for item in streams:
            url = item.get("url")
            if not url:
                continue
            quality = item.get("qualityLabel") or item.get("quality") or ""
            container = item.get("container") or ""
            try:
                height = int("".join(ch for ch in quality if ch.isdigit()) or 0)
            except ValueError:
                height = 0
            candidates.append((height, container == "mp4", item))
        if not candidates:
            errors.append(f"{base}: no formatStreams")
            continue
        _, _, selected = max(candidates, key=lambda x: (x[1], min(x[0], 1080), x[0]))
        stream_url = urljoin(base + "/", selected["url"])
        parsed = urlparse(stream_url)
        print("quality=", selected.get("qualityLabel") or selected.get("quality"))
        print("stream_host=", parsed.hostname)
        print("proxied=", parsed.hostname == urlparse(base).hostname)

        with requests.get(
            stream_url,
            stream=True,
            timeout=180,
            headers={"User-Agent": "Mozilla/5.0", "Referer": base + "/"},
            allow_redirects=True,
        ) as dl:
            print("download_status=", dl.status_code)
            print("final_host=", urlparse(dl.url).hostname)
            print("content_type=", dl.headers.get("content-type"))
            if dl.status_code != 200:
                errors.append(f"{base}: download {dl.status_code}")
                continue
            with output.open("wb") as fh:
                for chunk in dl.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        size = output.stat().st_size if output.exists() else 0
        print("downloaded_bytes=", size)
        if size > 0:
            print("successful_instance=", base)
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        errors.append(f"{base}: {type(exc).__name__}: {exc}")
        print("instance_error=", errors[-1])

print("errors=", " | ".join(errors))
raise SystemExit(1)
