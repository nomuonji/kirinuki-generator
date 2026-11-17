"""Acquire an explicitly authorized Bilibili part using BBDown 1.6.3.

No proxies, credentials, access-control workarounds, or publication. The
caller must establish permission for the source and subtitles first.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BVID = re.compile(r"BV[A-Za-z0-9]{10}")
TIMESTAMP = re.compile(r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})")
TIMING = re.compile(r"(\S+)\s+-->\s+(\S+)(?:\s+.*)?")
MAX_SUBTITLE_BYTES = 8 * 1024 * 1024


def source_url(bvid: str, page: int) -> str:
    if not BVID.fullmatch(bvid) or page < 1:
        raise ValueError("Expected a BV video ID and a positive part number")
    return f"https://www.bilibili.com/video/{bvid}/?p={page}"


def _seconds(value: str) -> float:
    match = TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("Invalid SRT timestamp")
    h, m, s, ms = map(int, match.groups())
    return (h * 3600000 + m * 60000 + s * 1000 + ms) / 1000


def parse_srt(path: Path, duration: float) -> list[dict]:
    if path.stat().st_size > MAX_SUBTITLE_BYTES:
        raise ValueError("SRT exceeds size limit")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid video duration")
    raw = path.read_text(encoding="utf-8-sig").strip()
    segments = []
    for block in re.split(r"\n[ \t]*\n+", raw):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2:
            raise ValueError("Incomplete subtitle cue")
        match = TIMING.fullmatch(lines[0].strip())
        if not match:
            raise ValueError("Invalid SRT cue timing")
        start, end = map(_seconds, match.groups())
        text = " ".join(line.strip() for line in lines[1:]).strip()
        if end <= start or start >= duration or end > duration + 2:
            raise ValueError("Subtitle interval is outside the selected video")
        end = min(end, duration)
        if text:
            segments.append({
                "start": round(start, 3), "end": round(end, 3),
                "duration": round(end - start, 3), "text": text,
            })
    if not segments:
        raise ValueError("No usable subtitle cues")
    return sorted(segments, key=lambda item: (item["start"], item["end"]))


def _track_language(path: Path) -> tuple[str, bool]:
    # BBDown uses <title>.<language-code>.srt (e.g. en-US / ai-zh).
    label = path.stem.rsplit(".", 1)[-1].lower().replace("_", "-")
    ai = label.startswith("ai-")
    parts = label[3:] if ai else label
    return parts.split("-", 1)[0], ai


def video_duration(path: Path) -> float:
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("No actual MP4 produced")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    data = json.loads(probe.stdout)
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    duration = float(data["format"]["duration"])
    if not {"audio", "video"} <= kinds or not math.isfinite(duration) or duration <= 0:
        raise ValueError("MP4 must contain both video and audio with positive duration")
    return duration


def _run_bbdown(url: str, page: int, directory: Path, options: list[str], timeout: int) -> None:
    exe = shutil.which("BBDown")
    if not exe:
        raise RuntimeError("Install BBDown 1.6.3 and ensure it is on PATH")
    command = [exe, url, "--select-page", str(page), *options]
    # Never echo the downloader's raw logs: these can contain signed media URLs
    # or untrusted video titles. Validate actual files even when its exit code is 0.
    with tempfile.TemporaryFile() as log:
        result = subprocess.run(command, cwd=directory, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"BBDown failed (exit {result.returncode})")


def download_video(bvid: str, page: int, output: Path) -> float:
    url = source_url(bvid, page)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bilibili-video-", dir=output.parent) as temp:
        directory = Path(temp)
        _run_bbdown(url, page, directory,
                    ["--skip-subtitle", "--skip-cover",
                     "--dfn-priority", "480P 清晰,720P 高清,360P 流畅",
                     "--encoding-priority", "avc,hevc,av1"], 2400)
        media = list(directory.rglob("*.mp4"))
        if len(media) != 1:
            raise RuntimeError(f"Expected one MP4 for the selected part, found {len(media)}")
        duration = video_duration(media[0])
        size = media[0].stat().st_size
        media[0].replace(output)
    print(f"BILIBILI_VIDEO bytes={size} duration={duration:.3f}")
    return duration


def download_transcript(bvid: str, page: int, video: Path, output: Path, language: str) -> list[dict]:
    url = source_url(bvid, page)
    duration = video_duration(video.resolve())
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bilibili-subs-", dir=output.parent) as temp:
        directory = Path(temp)
        _run_bbdown(url, page, directory, ["--sub-only", "--skip-ai", "false"], 180)
        matches = []
        for path in directory.rglob("*.srt"):
            family, ai = _track_language(path)
            if family != language:
                continue
            try:
                segments = parse_srt(path, duration)
            except (ValueError, UnicodeError, OSError):
                continue
            matches.append((ai, -len(segments), path.name, segments))
        if not matches:
            raise RuntimeError(f"No valid {language} subtitle track for selected Bilibili part")
        ai, _, _, segments = min(matches, key=lambda item: item[:3])
        candidate = directory / "transcript.json"
        candidate.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
        candidate.replace(output)
    print(f"BILIBILI_SUBTITLES language={language} ai={ai} cues={len(segments)} "
          f"last_end={segments[-1]['end']:.3f} video_duration={duration:.3f}")
    return segments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["video", "transcript"])
    parser.add_argument("bvid")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--language", choices=["ja", "zh", "en"], default="ja")
    parser.add_argument("--video", type=Path, default=Path("tmp/video.mp4"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rights-confirmed", action="store_true",
                        help="Confirm authorization to acquire and process this specific source")
    args = parser.parse_args()
    if not args.rights_confirmed:
        parser.error("Source and subtitle use must be authorized")
    if args.operation == "video":
        download_video(args.bvid, args.page, args.output)
    else:
        download_transcript(args.bvid, args.page, args.video, args.output, args.language)


if __name__ == "__main__":
    main()
