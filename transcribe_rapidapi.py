import argparse
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional

import requests
from dotenv import load_dotenv

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )
except ImportError:  # pragma: no cover - optional dependency
    YouTubeTranscriptApi = None  # type: ignore[misc]


def _normalize_segments(raw_segments: Iterable[dict]) -> List[dict]:
    """Normalize raw transcript items into {start,end,text} tuples."""

    def _to_float(value: object) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    normalized: List[dict] = []
    for seg in raw_segments:
        start = (
            _to_float(seg.get("start"))
            or _to_float(seg.get("offset"))
            or _to_float(seg.get("time"))
        )
        if start is None:
            continue

        if "end" in seg:
            end = _to_float(seg.get("end"))
        else:
            duration = (
                _to_float(seg.get("duration"))
                or _to_float(seg.get("dur"))
                or _to_float(seg.get("d"))
            )
            end = start + duration if duration is not None else None

        if end is None or end <= start:
            continue

        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        normalized.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "text": text,
            }
        )

    return normalized


def _decode_json_response(response: requests.Response) -> Optional[dict]:
    """Decode a JSON response, trying multiple encodings if needed."""
    possible_encodings = [
        "utf-8",
        response.encoding,
        "utf-8-sig",
        "cp932",
        "shift_jis",
    ]
    for enc in possible_encodings:
        if not enc:
            continue
        try:
            text = response.content.decode(enc)
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def fetch_transcript_from_youtube(video_id: str, preferred_languages: Iterable[str]) -> Optional[List[dict]]:
    if YouTubeTranscriptApi is None:
        return None
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=list(preferred_languages))
        return fetched.to_raw_data()
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception as exc:
        print(f"Warning: youtube_transcript_api failed: {exc}")
        return None


def fetch_transcript_from_rapidapi_1(video_id: str, api_key: str, language: str) -> Optional[List[dict]]:
    url = f"https://youtube-captions-transcript-subtitles-video-combiner.p.rapidapi.com/download-json/{video_id}"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "youtube-captions-transcript-subtitles-video-combiner.p.rapidapi.com",
    }
    try:
        response = requests.get(url, headers=headers, params={"language": language}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"API 1 error: {exc}")
        return None

    data = _decode_json_response(response)
    if isinstance(data, list) and data:
        return data
    print("API 1 returned no usable transcript.")
    return None


def fetch_transcript_from_rapidapi_2(video_id: str, api_key: str) -> Optional[List[dict]]:
    url = "https://youtube-transcript3.p.rapidapi.com/api/transcript"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "youtube-transcript3.p.rapidapi.com",
    }
    try:
        response = requests.get(url, headers=headers, params={"videoId": video_id}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"API 2 error: {exc}")
        return None

    data = _decode_json_response(response)
    if isinstance(data, dict) and "transcript" in data:
        data = data["transcript"]
    if isinstance(data, list) and data:
        return data
    print("API 2 returned no usable transcript.")
    return None


def save_transcript(segments: List[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Transcript saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a transcript for the given YouTube video.")
    parser.add_argument("video_id", help="YouTube video ID.")
    parser.add_argument("--lang", default="ja", help="Preferred language code (default: ja).")
    parser.add_argument("--output", default="tmp/transcript.json", help="Output path for the transcript JSON.")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("RAPIDAPI_KEY")

    language_preferences: List[str] = []
    for code in (args.lang, "ja", "ja-JP", "en", "en-US"):
        if code and code not in language_preferences:
            language_preferences.append(code)

    segments: Optional[List[dict]] = fetch_transcript_from_youtube(args.video_id, language_preferences)

    if not segments and api_key:
        segments = fetch_transcript_from_rapidapi_1(args.video_id, api_key, args.lang)

    if not segments and api_key:
        segments = fetch_transcript_from_rapidapi_2(args.video_id, api_key)

    if not segments:
        raise SystemExit("Failed to fetch transcript from all providers.")

    normalized = _normalize_segments(segments)
    if not normalized:
        raise SystemExit("Transcript was fetched but contained no usable items.")

    output_path = Path(args.output)
    save_transcript(normalized, output_path)


if __name__ == "__main__":
    main()
