"""Read channel metadata and test media retrieval without production side effects."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

CHANNELS = {
    "primary": "UCzXVsEc1h2Elljge0fnQYRg",
    "secondary": "UCj14-CcW0idWlvh3kQp683A",
    "tertiary": "UC0yQ2h4gQXmVUFWZSqlMVOA",
}


def api(resource, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = "https://www.googleapis.com/youtube/v3/" + resource + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except Exception as exc:
        # HTTP exception URLs include the API key; never print them.
        raise RuntimeError("YouTube metadata API failed: " + type(exc).__name__) from None


def duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    return sum(int(x or 0) * weight for x, weight in zip(match.groups(), (3600, 60, 1))) if match else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=CHANNELS)
    args = parser.parse_args()
    channel = api("channels", part="snippet,contentDetails", id=CHANNELS[args.lane])["items"][0]
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = []
    page = None
    for _ in range(2):
        params = dict(part="contentDetails", playlistId=playlist, maxResults=50)
        if page:
            params["pageToken"] = page
        response = api("playlistItems", **params)
        ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
        page = response.get("nextPageToken")
        if not page:
            break
    videos = []
    for offset in range(0, len(ids), 50):
        videos.extend(api("videos", part="snippet,contentDetails", id=",".join(ids[offset:offset+50])).get("items", []))
    candidates = []
    report = {"lane": args.lane, "channelId": channel["id"], "channelTitle": channel["snippet"]["title"],
              "fetched": len(videos), "regionBlockedUS": 0, "longForm": 0,
              "attempts": [], "downloadVerified": False, "productionChanged": False}
    for video in videos:
        snippet = video["snippet"]
        details = video["contentDetails"]
        if snippet.get("liveBroadcastContent") in {"live", "upcoming"}:
            continue
        if not 360 <= duration(details.get("duration")) <= 21600:
            continue
        report["longForm"] += 1
        restriction = details.get("regionRestriction", {})
        if (restriction.get("allowed") and "US" not in restriction["allowed"]) or "US" in restriction.get("blocked", []):
            report["regionBlockedUS"] += 1
            continue
        candidates.append(video)
    report["eligibleLongFormUS"] = len(candidates)
    report["latestUploads"] = [{"videoId": v["id"], "title": v["snippet"]["title"],
                                "publishedAt": v["snippet"]["publishedAt"],
                                "duration": v["contentDetails"].get("duration"),
                                "regionRestriction": v["contentDetails"].get("regionRestriction")} for v in videos[:5]]
    with tempfile.TemporaryDirectory() as directory:
        for video in candidates[:2]:
            attempt = {"videoId": video["id"], "title": video["snippet"]["title"],
                       "publishedAt": video["snippet"]["publishedAt"], "backend": "SaveTube"}
            report["attempts"].append(attempt)
            output = Path(directory) / "source.mp4"
            try:
                subprocess.run(["node", "scripts/savetube_download.mjs", video["id"], str(output), "720"], check=True, timeout=240)
                result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)], capture_output=True, text=True, check=True, timeout=30)
                media = json.loads(result.stdout)
                kinds = {stream["codec_type"] for stream in media["streams"]}
                actual = float(media["format"]["duration"])
                expected = duration(video["contentDetails"]["duration"])
                if not {"video", "audio"}.issubset(kinds) or abs(actual - expected) > max(5, expected * .02):
                    raise RuntimeError("missing_stream_or_incomplete_download")
                subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-t", "10", "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], check=True, timeout=60)
                attempt.update(verified=True, bytes=output.stat().st_size, durationSeconds=actual, streams=sorted(kinds))
                report["downloadVerified"] = True
                break
            except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
                attempt.update(verified=False, failure=type(exc).__name__)
            finally:
                output.unlink(missing_ok=True)
    report["result"] = "media_verified" if report["downloadVerified"] else "download_failed" if candidates else "no_US_eligible_longform"
    Path(f"probe-{args.lane}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Reports are diagnostic data; no candidate is not a proven successful download.
    return 0 if report["downloadVerified"] or not candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
