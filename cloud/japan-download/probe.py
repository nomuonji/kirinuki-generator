"""Credential-free, bounded Cloud Run experiment; never publishes a clip."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile


def run(command, timeout):
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError("timeout") from None
    if process.returncode:
        message = stderr.lower()
        if "not a bot" in message or "sign in" in message:
            reason = "authentication_required"
        elif "country" in message or "geo" in message:
            reason = "geo_restricted"
        elif "403" in message:
            reason = "http_403"
        else:
            reason = "media_command_failed"
        # Avoid logging signed media URLs or future authentication material.
        raise RuntimeError(reason)
    return stdout


def verify(path):
    info = json.loads(run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ], 30))
    streams = info.get("streams", [])
    kinds = {stream.get("codec_type") for stream in streams}
    duration = float(info.get("format", {}).get("duration", 0))
    if not {"video", "audio"}.issubset(kinds):
        raise RuntimeError("missing_audio_or_video")
    if not 25 <= duration <= 45:
        raise RuntimeError("unexpected_sample_duration")
    # Container metadata alone is insufficient: decode the entire sample.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], 60)
    return {"durationSeconds": round(duration, 3),
            "bytes": path.stat().st_size,
            "streams": sorted(kinds), "decoded": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id):
        parser.error("Expected an 11-character YouTube video ID")
    result = {"videoId": args.video_id, "region": "asia-northeast1",
              "regionBasis": "deployment configuration; egress country unverified",
              "passed": False}
    try:
        result["ytDlpVersion"] = run([sys.executable, "-m", "yt_dlp", "--version"], 10).strip()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.mp4"
            run([
                sys.executable, "-m", "yt_dlp", "--ignore-config",
                "--no-playlist", "--no-progress", "--no-warnings",
                "--js-runtimes", "node", "--socket-timeout", "20",
                "--retries", "1", "--fragment-retries", "1",
                "--extractor-retries", "1", "--download-sections", "*0-30",
                "-f", "bv*[height<=720]+ba/b[height<=720]",
                "--merge-output-format", "mp4", "--remux-video", "mp4",
                "-o", str(output),
                "https://www.youtube.com/watch?v=" + args.video_id,
            ], 420)
            result.update(verify(output))
            result["passed"] = True
    except (RuntimeError, OSError, ValueError) as exc:
        result["failure"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
