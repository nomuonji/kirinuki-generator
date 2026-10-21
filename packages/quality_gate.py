"""Fail-closed editorial and media QA for unattended clip production.

A transcript review cannot certify rights, transformative use, or YouTube monetization.
This module prevents obvious bad clips entering the shared posting stock.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path

AUDIT_FILENAME = ".quality_audit.json"
AUDIT_VERSION = 1


def _get(candidate, name, default=None):
    return candidate.get(name, default) if isinstance(candidate, dict) else getattr(candidate, name, default)


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).replace("**", "")
    return re.sub(r"[\W_]+", "", value).casefold()


def _digest(data) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def candidate_payload(candidates) -> list[dict]:
    return [
        {key: _get(c, key) for key in ("start", "end", "title", "punchline", "reason", "confidence")}
        for c in candidates
    ]


def static_filter(candidates, segments, *, min_confidence: float = 0.76,
                  min_sec: float = 30, max_sec: float = 120,
                  min_gap: float = 30) -> tuple[list, list[dict]]:
    """Reject timestamp/quotation mistakes, near-duplicates and empty conversations."""
    source_end = max((float(s["end"]) for s in segments), default=0.0)
    approved = []
    decisions = []
    ranked = sorted(candidates, key=lambda c: float(_get(c, "confidence", 0) or 0), reverse=True)
    for c in ranked:
        start, end = float(_get(c, "start", -1)), float(_get(c, "end", -1))
        confidence = float(_get(c, "confidence", 0) or 0)
        quote = _plain(_get(c, "punchline", ""))
        excerpt = [s for s in segments if float(s["end"]) > start and float(s["start"]) < end]
        whole_text = _plain(" ".join(str(s.get("text", "")) for s in excerpt))
        reason = "approved"
        if confidence < min_confidence:
            reason = "weak_model_confidence"
        elif start < 0 or end <= start or end > source_end + 0.5 or not min_sec <= end - start <= max_sec:
            reason = "invalid_boundaries"
        elif not _plain(_get(c, "title", "")) or len(str(_get(c, "title", ""))) > 90:
            reason = "invalid_title"
        elif len(whole_text) < 40 or len(excerpt) < 3:
            reason = "insufficient_dialogue"
        elif len(quote) < 2 or len(quote) > 65 or quote not in whole_text:
            reason = "unsupported_punchline"
        elif not str(_get(c, "reason", "")).strip():
            reason = "missing_editorial_reason"
        elif any(start < float(_get(prev, "end")) + min_gap and
                 float(_get(prev, "start")) < end + min_gap for prev in approved):
            reason = "overlapping_or_repetitive"
        if reason == "approved":
            approved.append(c)
        decisions.append({"start": start, "end": end, "decision": reason})
    approved.sort(key=lambda c: float(_get(c, "start")))
    return approved, decisions


def independent_review(candidates, segments, *, model_name: str | None = None) -> tuple[list, list[dict]]:
    """A separate low-temperature Gemini pass; API/JSON failures reject all clips."""
    if not candidates:
        return [], []
    import os
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Editorial review requires GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    payload = []
    for i, c in enumerate(candidates):
        excerpt = [
            str(s.get("text", "")) for s in segments
            if float(s["end"]) > float(_get(c, "start"))
            and float(s["start"]) < float(_get(c, "end"))
        ]
        payload.append({
            "index": i, "title": _get(c, "title"), "punchline": _get(c, "punchline"),
            "reason": _get(c, "reason"), "excerpt": " ".join(excerpt)[:11000]
        })
    prompt = (
        "You are an independent Japanese short-form editorial auditor, NOT the writer. "
        "Evaluate each excerpt against its proposed title and punchline. "
        "PASS only if a first-time viewer understands the topic without the longer source, "
        "the question or claim is clearly answered, the ending is not abrupt, the title "
        "does not misrepresent the excerpt, and a concrete insight/surprise/punchline exists. "
        "Be skeptical: conversational filler, unsupported claims, invented context, misleading "
        "drama and clips with missing setup must FAIL. Judge ONLY the supplied transcript; "
        "do not assume that reuse has copyright permission or is monetizable. "
        "Return JSON array with exactly one object per index: "
        '{"index":0,"pass":true,"sourceSupported":true,"standalone":true,'
        '"completeEnding":true,"payoff":true,"reason":"短い具体的説明"}. '
        "No markdown. All booleans must be genuine JSON booleans."
    )
    model = genai.GenerativeModel(model_name or os.environ.get("KIRINUKI_REVIEW_MODEL", "gemini-2.5-flash"))
    response = model.generate_content(
        [prompt, json.dumps(payload, ensure_ascii=False)],
        generation_config={"response_mime_type": "application/json", "temperature": 0},
        request_options={"timeout": 300},
    )
    try:
        reviewed = json.loads(response.text)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError("Independent editorial review returned invalid JSON") from exc
    if not isinstance(reviewed, list) or len(reviewed) != len(candidates):
        raise RuntimeError("Independent editorial review returned an incomplete response")
    decisions = {}
    for d in reviewed:
        if not isinstance(d, dict) or type(d.get("index")) is not int:
            raise RuntimeError("Independent editorial review returned invalid indices")
        idx = d["index"]
        if idx in decisions or idx < 0 or idx >= len(candidates):
            raise RuntimeError("Independent editorial review duplicated an index")
        decisions[idx] = d
    approved = []
    audit = []
    for i, c in enumerate(candidates):
        d = decisions[i]
        allow = all(d.get(k) is True for k in ("pass", "sourceSupported", "standalone", "completeEnding", "payoff"))
        audit.append({"index": i, "start": float(_get(c, "start")), "approved": allow,
                      "reason": str(d.get("reason", ""))[:300]})
        if allow:
            approved.append(c)
    return approved, audit


def write_receipt(folder: Path, candidates, decisions: list[dict]) -> None:
    data = {
        "version": AUDIT_VERSION, "candidateDigest": _digest(candidate_payload(candidates)),
        "approvedCount": len(candidates), "independentReview": decisions,
    }
    (folder / AUDIT_FILENAME).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validated_receipt(folder: Path) -> bool:
    try:
        receipt = json.loads((folder / AUDIT_FILENAME).read_text(encoding="utf-8"))
        candidates = json.loads((folder / "clip_candidates.json").read_text(encoding="utf-8"))
        return (
            receipt.get("version") == AUDIT_VERSION
            and receipt.get("approvedCount") == len(candidates)
            and len(candidates) > 0
            and receipt.get("candidateDigest") == _digest(candidate_payload(candidates))
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def verify_rendered_media(path: Path) -> dict:
    """Require a decodable vertical clip with real video and audio before Drive upload."""
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError("Media QA: clip missing or abnormally small")
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=35,
        )
        info = json.loads(probe.stdout)
        streams = info.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        audio = next(s for s in streams if s.get("codec_type") == "audio")
        duration = float(info.get("format", {}).get("duration") or 0)
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if not 18 <= duration <= 135:
            raise RuntimeError(f"Media QA: invalid duration {duration:.1f}s")
        if width < 400 or height < 640 or height <= width:
            raise RuntimeError(f"Media QA: invalid vertical dimensions {width}x{height}")
        if int(audio.get("channels") or 0) < 1:
            raise RuntimeError("Media QA: no audio channels")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-t", "3",
             "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            check=True, capture_output=True, text=True, timeout=50,
        )
        return {"durationSeconds": round(duration, 2), "width": width, "height": height,
                "audioChannels": int(audio["channels"]), "sizeBytes": path.stat().st_size}
    except (StopIteration, KeyError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"Media QA failed: {exc}") from exc
