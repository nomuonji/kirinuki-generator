import argparse
import json
import os
import pathlib
import re
import sys
import textwrap
from typing import Any, Dict, List

import google.generativeai as genai
from dotenv import load_dotenv

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TRANSCRIPT_LINES = 160
MAX_TRANSCRIPT_CHARS = 6500


def _load_transcript(path: pathlib.Path) -> List[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Transcript file must be JSON: {exc}") from exc

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("segments"), list):
        items = payload["segments"]
    else:
        raise ValueError("Transcript JSON must be a list of segments or include a 'segments' list")

    segments: List[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start") or item.get("startTime") or 0.0)
            duration = float(item.get("dur") or item.get("duration") or item.get("durationSec") or 0.0)
        except (TypeError, ValueError):
            continue
        end = start + max(duration, 0.0)
        if end <= start:
            continue
        segments.append({"start": start, "end": end, "text": text})

    if not segments:
        raise ValueError("Transcript did not contain any usable segments")
    return segments


def _window_segments(
    segments: List[dict[str, Any]], start_sec: float, end_sec: float
) -> List[dict[str, Any]]:
    windowed: List[dict[str, Any]] = []
    for seg in segments:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        if seg_end <= start_sec or seg_start >= end_sec:
            continue
        overlap_start = max(seg_start, start_sec)
        overlap_end = min(seg_end, end_sec)
        if overlap_end <= overlap_start:
            continue
        windowed.append(
            {
                "start": overlap_start - start_sec,
                "duration": overlap_end - overlap_start,
                "text": seg["text"],
            }
        )
    return windowed


def _format_segments(segments: List[dict[str, Any]]) -> List[str]:
    lines = [
        f"- [{seg['start']:.2f}s -> {seg['start'] + seg['duration']:.2f}s] {seg['text']}"
        for seg in segments
    ]
    if len(lines) > MAX_TRANSCRIPT_LINES:
        head = lines[: MAX_TRANSCRIPT_LINES - 20]
        tail = lines[-10:]
        lines = head + ["... (snipped for brevity) ..."] + tail
    joined = "\n".join(lines)
    if len(joined) > MAX_TRANSCRIPT_CHARS:
        joined = joined[: MAX_TRANSCRIPT_CHARS - 80] + "\n... (snipped for brevity) ..."
    return joined.split("\n")



def _build_single_prompt(
    character_name: str,
    transcript_lines: List[str],
    clip_duration: float,
    max_reactions: int,
    tone: str | None,
) -> str:
    tone_clause = f"The character's vibe is {tone}." if tone else ""
    tone_clause_line = f"{tone_clause}\n" if tone_clause else ""
    transcript_block = "\n".join(transcript_lines)
    json_shape = '{"reactions": [{"startTimeSec": number, "durationSec": number, "text": string, "emotion": string}]}'

    prompt = (
        f'You are scripting short, lively commentary lines for the mascot character "{character_name}".\n'
        f'{tone_clause_line}'
        f'The character watches a clip that lasts {clip_duration:.2f} seconds and reacts in Japanese with short phrases '
        '(max 16 Japanese characters per sentence, up to 3 sentences each reaction).\n'
        'Base the reactions on this transcript, where timestamps are relative to the start of the clip:\n\n'
        f'{transcript_block}\n\n'
        'Follow the rules:\n'
        f'1. Output **JSON only** with shape: {json_shape}.\n'
        f'2. startTimeSec must be between 0 and {clip_duration:.2f}.\n'
        '3. Each reaction duration between 1.2 and 4.5 seconds and must stay inside the clip.\n'
        '4. Keep the character voice consistent and fun; emotion should be a short descriptor like "Excited" or "Surprised".\n'
        f'5. Limit to {max_reactions} reactions.\n'
        '6. Keep reactions chronological and anchor each startTimeSec to the transcript lines that trigger it—wait until those lines finish (about 0.3s later) before the reaction begins, and never let reactions overlap.\n\n'
        'Return valid JSON with double quotes and no extra commentary.\n'
    )
    return textwrap.dedent(prompt).strip()


def _build_bulk_prompt(
    character_name: str,
    clip_payloads: List[dict[str, Any]],
    max_reactions: int,
    tone: str | None,
) -> str:
    tone_clause = f"The character's vibe is {tone}." if tone else ""
    tone_clause_line = f"{tone_clause}\n" if tone_clause else ""
    sections: List[str] = []
    for payload in clip_payloads:
        sections.append(
            f'Clip {payload["clip_id"]} ({payload["duration"]:.2f}s) transcription (timestamps are relative to the clip start):'
        )
        sections.extend(payload["lines"])
        sections.append("")
    sections_text = "\n".join(sections).strip()
    json_shape = '{"clips": [{"clipId": string, "reactions": [{"startTimeSec": number, "durationSec": number, "text": string, "emotion": string}]}]}'

    prompt = (
        f'You are scripting short, lively commentary lines for the mascot character "{character_name}".\n'
        f'{tone_clause_line}'
        f'Multiple clips are provided below. For each clip, craft up to {max_reactions} Japanese reaction snippets that feel like real-time commentary. '
        'Keep each sentence under 16 Japanese characters and at most 3 sentences per reaction.\n\n'
        'Clips:\n'
        f'{sections_text}\n\n'
        'Rules:\n'
        f'1. Respond with **JSON only** having the shape: {json_shape}.\n'
        '2. Use the provided clipId values exactly as given.\n'
        '3. startTimeSec values are relative to the beginning of each clip (0.0 = clip start) and must lie within the clip duration.\n'
        '4. durationSec must be between 1.2 and 4.5 seconds and keep the reaction within the clip.\n'
        '5. Keep the character voice consistent and fun; emotion should be a short descriptor like "Excited" or "Surprised".\n'
        '6. Align each reaction with the transcript timing—trigger it shortly after the relevant lines conclude (≈0.3s later) and maintain chronological order without overlaps.\n'
        '7. Avoid extra commentary outside the JSON.\n'
    )
    return textwrap.dedent(prompt).strip()


def _candidate_texts(response: Any) -> List[str]:
    texts: List[str] = []

    response_text = getattr(response, "text", None)
    if response_text:
        texts.append(str(response_text))

    candidates = getattr(response, "candidates", None)
    if not candidates:
        return texts

    for candidate in candidates:
        if candidate is None:
            continue

        parts = []
        content = getattr(candidate, "content", None)
        if content is not None:
            parts = getattr(content, "parts", None) or []
        if not parts:
            parts = getattr(candidate, "parts", None) or []

        part_texts: List[str] = []
        for part in parts:
            if part is None:
                continue
            text_value = getattr(part, "text", None)
            if text_value:
                part_texts.append(str(text_value))
                continue

            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None:
                data = getattr(inline_data, "data", None)
                if isinstance(data, (bytes, bytearray)):
                    part_texts.append(data.decode("utf-8", errors="ignore"))
                    continue
                if isinstance(data, str):
                    part_texts.append(data)
                    continue

            json_value = getattr(part, "json", None)
            if json_value:
                part_texts.append(json.dumps(json_value, ensure_ascii=False))
                continue

            if hasattr(part, "to_dict"):
                try:
                    part_dict = part.to_dict()
                except Exception:
                    part_dict = None
                if isinstance(part_dict, dict):
                    if "text" in part_dict and part_dict["text"]:
                        part_texts.append(str(part_dict["text"]))
                        continue
                    if "json" in part_dict and part_dict["json"]:
                        part_texts.append(json.dumps(part_dict["json"], ensure_ascii=False))
                        continue

        if part_texts:
            texts.append("".join(part_texts))
            continue

        if hasattr(candidate, "to_dict"):
            try:
                cand_dict = candidate.to_dict()
            except Exception:
                cand_dict = None
            if cand_dict:
                try:
                    texts.append(json.dumps(cand_dict, ensure_ascii=False))
                except TypeError:
                    pass

    return texts


def _call_gemini(model_name: str, prompt: str, *, retries: int = 2) -> dict[str, Any]:
    model = genai.GenerativeModel(model_name)
    generation_config = genai.types.GenerationConfig(
        response_mime_type="application/json",
        temperature=0.7,
    )

    attempts: List[str] = []
    for attempt in range(retries + 1):
        prompt_variant = prompt
        if attempt > 0:
            prompt_variant = prompt + "\n\nREMINDER: Respond with JSON only. No prose."

        try:
            response = model.generate_content(
                contents=[prompt_variant],
                generation_config=generation_config,
            )
        except Exception as exc:
            attempts.append(f"generation_error:{exc}")
            continue

        for text in _candidate_texts(response):
            parsed = _extract_json(text)
            if parsed is not None:
                return parsed

        texts = _candidate_texts(response)
        snippet = (texts[0][:400] + "...") if texts else "<no text>"
        attempts.append(f"unparsed:{snippet}")

    details = "; ".join(attempts) or "no_attempts"
    raise RuntimeError(f"Gemini API did not return valid JSON content ({details})")

def _extract_json(value: str) -> dict[str, Any] | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, flags=re.S)
    if fenced_match:
        try:
            return json.loads(fenced_match.group(1))
        except json.JSONDecodeError:
            return None

    brace_match = re.search(r"\{.*\}", value, flags=re.S)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _sanitize_reaction_entries(
    raw_entries: Any,
    *,
    max_reactions: int,
    clip_duration: float,
    segments: List[dict[str, Any]] | None = None,
) -> List[dict[str, Any]]:
    if not isinstance(raw_entries, list):
        print("  -> Warning: Missing or invalid 'reactions' list; falling back to empty list.", file=sys.stderr)
        return []

    cleaned: List[dict[str, Any]] = []
    last_end = 0.0
    min_duration = min(0.8, clip_duration) if clip_duration > 0 else 0.0

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        try:
            start_sec = float(
                entry.get("startTimeSec")
                or entry.get("start")
                or entry.get("timeSec")
                or 0
            )
            duration_sec = float(
                entry.get("durationSec")
                or entry.get("duration")
                or entry.get("lenSec")
                or entry.get("lengthSec")
                or 0
            )
        except (TypeError, ValueError):
            continue
        if duration_sec <= 0:
            continue

        base_start = max(0.0, start_sec + 0.35)
        anchor = None
        if segments:
            for seg in segments:
                try:
                    seg_start = float(seg.get("start", 0.0))
                    seg_duration = float(seg.get("duration", 0.0))
                except (TypeError, ValueError):
                    continue
                seg_end = seg_start + max(seg_duration, 0.0)
                if base_start <= seg_end + 0.05:
                    anchor = seg_end + 0.2
                    break
            if anchor is None and segments:
                last_seg = segments[-1]
                try:
                    seg_start = float(last_seg.get("start", 0.0))
                    seg_duration = float(last_seg.get("duration", 0.0))
                except (TypeError, ValueError):
                    seg_start = 0.0
                    seg_duration = 0.0
                anchor = seg_start + max(seg_duration, 0.0) + 0.2
        if anchor is not None:
            base_start = max(base_start, anchor)

        latest_start = max(0.0, clip_duration - 0.5)
        start_clamped = max(last_end + 0.25, min(base_start, latest_start))
        max_possible = max(0.0, clip_duration - start_clamped)
        if max_possible <= 0.25:
            continue

        duration_clamped = min(duration_sec, max_possible)
        if min_duration > 0 and duration_clamped < min_duration:
            if max_possible >= min_duration:
                duration_clamped = min_duration
            else:
                duration_clamped = max_possible
        if duration_clamped <= 0.25:
            continue

        reaction: dict[str, Any] = {
            "startTimeSec": round(start_clamped, 3),
            "durationSec": round(duration_clamped, 3),
            "text": text,
        }
        emotion = entry.get("emotion") or entry.get("mood")
        if isinstance(emotion, str) and emotion.strip():
            reaction["emotion"] = emotion.strip()
        cleaned.append(reaction)
        last_end = start_clamped + duration_clamped
        if len(cleaned) >= max_reactions:
            break

    return cleaned
def _sanitize_bulk_reactions(
    payload: dict[str, Any],
    clip_meta: Dict[str, dict[str, Any]],
    max_reactions: int,
) -> Dict[str, List[dict[str, Any]]]:
    clips = payload.get("clips")
    if not isinstance(clips, list):
        print("Warning: Gemini response missing 'clips' array; treating as no reactions.", file=sys.stderr)
        clips = []

    sanitized: Dict[str, List[dict[str, Any]]] = {}
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        clip_id = (
            str(clip.get("clipId") or clip.get("clip_id") or clip.get("id") or "").strip()
        )
        if not clip_id:
            continue
        if clip_id not in clip_meta:
            continue
        duration = clip_meta[clip_id]["duration"]
        reactions = _sanitize_reaction_entries(
            clip.get("reactions", []),
            max_reactions=max_reactions,
            clip_duration=duration,
            segments=clip_meta[clip_id].get("segments"),
        )
        sanitized[clip_id] = reactions

    # Ensure we have entries for every clip, even if empty
    for clip_id in clip_meta:
        sanitized.setdefault(clip_id, [])

    return sanitized

def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate mascot reaction timelines via Gemini API.")
    parser.add_argument("--transcript", required=True, help="Path to transcript JSON (list of segments).")
    parser.add_argument("--output", help="Output JSON path when generating a single clip timeline.")
    parser.add_argument("--output-dir", help="Directory for per-clip reaction JSON when generating in bulk.")
    parser.add_argument("--clip-candidates", help="Path to clip_candidates.json for bulk generation.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model ID.")
    parser.add_argument("--max-reactions", type=int, default=8, help="Max reactions to request per clip.")
    parser.add_argument("--character-name", default="Kirinuki Friend", help="Name of the reaction character.")
    parser.add_argument("--tone", help="Optional short description of the character tone.")
    parser.add_argument("--start-sec", type=float, help="Clip start second (single mode).")
    parser.add_argument("--end-sec", type=float, help="Clip end second (single mode).")
    parser.add_argument("--api-key", help="Gemini API key. Overrides GEMINI_API_KEY env var if provided.")

    args = parser.parse_args(argv)

    load_dotenv()

    transcript_path = pathlib.Path(args.transcript).expanduser().resolve()
    if not transcript_path.exists():
        parser.error(f"Transcript file not found: {transcript_path}")

    try:
        segments = _load_transcript(transcript_path)
    except ValueError as exc:
        parser.error(str(exc))

    single_mode = args.start_sec is not None or args.end_sec is not None or args.output is not None

    api_key = args.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        parser.error("Gemini API key missing. Pass --api-key or set GEMINI_API_KEY.")
    
    genai.configure(api_key=api_key)

    if single_mode:
        if args.start_sec is None or args.end_sec is None:
            parser.error("--start-sec and --end-sec are required for single clip generation.")
        if args.end_sec <= args.start_sec:
            parser.error("--end-sec must be greater than --start-sec.")
        window_segments = _window_segments(segments, args.start_sec, args.end_sec)
        if not window_segments:
            parser.error("No transcript segments remain after clipping.")
        clip_duration = args.end_sec - args.start_sec
        transcript_lines = _format_segments(window_segments)
        prompt = _build_single_prompt(
            args.character_name,
            transcript_lines,
            clip_duration,
            args.max_reactions,
            args.tone,
        )
        try:
            response_payload = _call_gemini(args.model, prompt)
            reactions = _sanitize_reaction_entries(
                response_payload.get("reactions", []),
                max_reactions=max(1, args.max_reactions),
                clip_duration=clip_duration,
                segments=window_segments,
            )
        except Exception as exc:
            parser.error(f"Gemini API error: {exc}")

        if args.output:
            output_path = pathlib.Path(args.output)
        else:
            output_path = transcript_path.with_name(transcript_path.stem + "_reactions.json")
        output_path.write_text(json.dumps({"reactions": reactions}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {len(reactions)} reactions -> {output_path}")
        return 0

    # Bulk mode
    project_root = pathlib.Path(__file__).resolve().parents[2]
    candidates_path = args.clip_candidates
    if candidates_path is None:
        default_candidates = project_root / "apps" / "remotion" / "public" / "out_clips" / "clip_candidates.json"
        if default_candidates.exists():
            candidates_path = str(default_candidates)
        else:
            parser.error("Bulk generation requires --clip-candidates to be specified.")
    candidates_path = pathlib.Path(candidates_path).expanduser().resolve()
    if not candidates_path.exists():
        parser.error(f"Clip candidates file not found: {candidates_path}")

    try:
        clip_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        parser.error(f"Failed to parse clip candidates JSON: {exc}")
    if not isinstance(clip_candidates, list) or not clip_candidates:
        parser.error("Clip candidates file did not contain a list of clips.")

    output_dir = pathlib.Path(args.output_dir).expanduser().resolve() if args.output_dir else candidates_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_payloads: List[dict[str, Any]] = []
    clip_meta: Dict[str, dict[str, Any]] = {}
    for index, clip in enumerate(clip_candidates, start=1):
        try:
            start = float(clip.get("start"))
            end = float(clip.get("end"))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        window_segments = _window_segments(segments, start, end)
        if not window_segments:
            clip_id = f"clip_{index:03d}"
            clip_meta[clip_id] = {"duration": end - start, "index": index, "segments": []}
            clip_payloads.append({
                "clip_id": clip_id,
                "duration": end - start,
                "lines": ["(no transcript available)"]
            })
            continue
        transcript_lines = _format_segments(window_segments)
        clip_id = f"clip_{index:03d}"
        duration = end - start
        clip_payloads.append(
            {
                "clip_id": clip_id,
                "duration": duration,
                "lines": transcript_lines,
            }
        )
        clip_meta[clip_id] = {"duration": duration, "index": index, "segments": window_segments}

    if not clip_payloads:
        parser.error("No valid clips found in candidates file.")

    prompt = _build_bulk_prompt(
        args.character_name,
        clip_payloads,
        max(1, args.max_reactions),
        args.tone,
    )

    try:
        response_payload = _call_gemini(args.model, prompt)
        sanitized_map = _sanitize_bulk_reactions(
            response_payload,
            clip_meta,
            max(1, args.max_reactions),
        )
    except Exception as exc:
        parser.error(f"Gemini API error: {exc}")

    for clip_id, meta in clip_meta.items():
        reactions = sanitized_map.get(clip_id, [])
        output_path = output_dir / f"{clip_id}_reactions.json"
        output_path.write_text(json.dumps({"reactions": reactions}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {len(reactions)} reactions -> {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
