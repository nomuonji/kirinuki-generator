import os, json, time
from typing import List, Dict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

import google.generativeai as genai
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
HOOK_MODEL = os.environ.get("HOOK_MODEL", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")
genai.configure(api_key=API_KEY)

class ClipCandidate(BaseModel):
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    title: str = ""
    reason: str = ""
    confidence: float = 0.5

def _chunks(items, max_chars=12000):
    buf, size = [], 0
    for it in items:
        line = f"[{it['start']:.2f}->{it['end']:.2f}] {it['text']}"
        # Add 1 for the newline character that will be added by join
        if size + len(line) + 1 > max_chars and buf:
            yield "\n".join(buf)
            buf, size = [], 0
        buf.append(line)
        # Add 1 for the newline character
        size += len(line) + 1
    if buf:
        yield "\n".join(buf)

def propose_clips_from_transcript(items: List[dict], preset="shorts", min_gap=30.0, min_sec=20.0, max_sec=90.0) -> List[ClipCandidate]:
    from google.generativeai import protos

    clip_schema = protos.Schema(
        type=protos.Type.ARRAY,
        items=protos.Schema(
            type=protos.Type.OBJECT,
            properties={
                "start": protos.Schema(type=protos.Type.NUMBER),
                "end": protos.Schema(type=protos.Type.NUMBER),
                "title": protos.Schema(type=protos.Type.STRING),
                "reason": protos.Schema(type=protos.Type.STRING),
                "confidence": protos.Schema(type=protos.Type.NUMBER),
            },
            required=["start", "end"],
        ),
    )

    sys = f"""You are a master video editor, specializing in creating viral short-form content. Your task is to analyze a timestamped transcript and identify the most compelling, self-contained clips.

**Your Goal:** Propose clips that are high-impact and feel complete.

**Key Principles:**
1.  **Content:** Focus on clear topic shifts, insightful Q&A, emotional peaks, strong opinions, or surprising moments (punchlines).
2.  **Pacing and Flow:** Each clip must represent a complete thought or a full thematic unit. It should not feel like it's cut off abruptly.
3.  **Natural Endings:** To achieve a professional feel, the end of a clip is critical. Prioritize ending a clip on a transcript segment that:
    - Concludes a sentence, marked by punctuation (e.g., '。', '！', '？', '.').
    - Is immediately followed by a noticeable pause or silence in the conversation.
    - Represents the end of a speaker's main point.
    - **Speaker Transitions:** Pay close attention to conversational turns. A point where one speaker finishes and another begins is an ideal clip boundary.
4.  **AVOID:** Do not end a clip mid-sentence, on a conjunction (like 'and', 'but', 'so'), or right before a person finishes their thought.

**Constraints:**
- Preset: {preset}
- Clip Length: {min_sec}s to {max_sec}s
- Minimum Gap Between Clips: {min_gap}s
- **Crucial:** The 'end' time for each proposed clip MUST exactly match the 'end' time of one of the transcript segments provided. Do not invent timestamps.

Output JSON only."""

    model = genai.GenerativeModel(GEMINI_MODEL)
    all_props: List[ClipCandidate] = []
    chunk_chars = int(os.environ.get("GEMINI_PROPOSAL_CHUNK_CHARS", "12000"))
    for chunk in _chunks(items, max_chars=chunk_chars):
        resp = model.generate_content(
            [sys, chunk],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": clip_schema,
                "temperature": 0.2
            },
        )
        parsed = _safe_parsed(resp, expect_array=True)
        for d in parsed:
            try:
                c = ClipCandidate(**d)
                dur = c.end - c.start
                if dur < min_sec or dur > max_sec or c.start < 0 or c.end <= c.start:
                    continue
                all_props.append(c)
            except Exception:
                continue

    # merge/clean
    all_props.sort(key=lambda x: x.start)
    merged: List[ClipCandidate] = []
    for c in all_props:
        if not merged:
            merged.append(c); continue
        last = merged[-1]
        if c.start - last.end < min_gap or c.start < last.end:
            keep = c if c.confidence >= last.confidence else last
            merged[-1] = keep
        else:
            merged.append(c)
    return merged


class HookText(BaseModel):
    upper: str = Field(..., description="Text to display at the top of the video. Should be a catchy, title-like hook.")
    lower: str = Field(..., description="Text to display at the bottom of the video. Should be a supplementary, engaging hook.")

def generate_hook_text(clip_transcript: str) -> HookText:
    """
    Generates catchy hook texts for a video clip based on its transcript.
    """
    from google.generativeai import protos

    hook_schema = protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "upper": protos.Schema(type=protos.Type.STRING),
            "lower": protos.Schema(type=protos.Type.STRING),
        },
        required=["upper", "lower"],
    )

    sys = (
        "You are a viral video producer. Based on the following transcript of a short video clip, "
        "generate two catchy hook texts to maximize viewer engagement. "
        "One text for the top of the video (a title-like hook) and one for the bottom (a supplementary hook). "
        "The texts should be short, impactful, and create curiosity. "
        "Output JSON only."
    )

    model = genai.GenerativeModel(HOOK_MODEL)
    resp = model.generate_content(
        [sys, clip_transcript],
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": hook_schema,
            "temperature": 0.7,
        },
    )
    parsed = _safe_parsed(resp)
    return HookText(**parsed)


def generate_hooks_bulk(clip_items: List[Dict]) -> Dict[int, HookText]:
    """
    Generate hook texts for multiple clips in a single Gemini call.
    clip_items: [{"index": int, "transcript": str}]
    Returns: {index: HookText}
    """
    from google.generativeai import protos

    result_schema = protos.Schema(
        type=protos.Type.ARRAY,
        items=protos.Schema(
            type=protos.Type.OBJECT,
            properties={
                "index": protos.Schema(type=protos.Type.NUMBER),
                "upper": protos.Schema(type=protos.Type.STRING),
                "lower": protos.Schema(type=protos.Type.STRING),
            },
            required=["index", "upper", "lower"],
        ),
    )

    sys = (
        "You are a viral video producer. For each item, create two short, punchy hooks.\n"
        "Return an array aligning 1:1 with input items by 'index'. Output JSON only."
    )

    # Build input payload compactly to stay under token limits
    payload = [{"index": int(it["index"]), "transcript": str(it.get("transcript", ""))[:4000]} for it in clip_items]

    model = genai.GenerativeModel(HOOK_MODEL)
    resp = model.generate_content(
        [sys, "INPUT:", json.dumps(payload, ensure_ascii=False)],
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": result_schema,
            "temperature": 0.7,
        },
    )
    parsed = _safe_parsed(resp, expect_array=True)
    out: Dict[int, HookText] = {}
    for obj in parsed:
        try:
            idx = int(obj.get("index"))
            out[idx] = HookText(upper=str(obj.get("upper", "")), lower=str(obj.get("lower", "")))
        except Exception:
            continue
    return out


def _safe_parsed(resp, expect_array: bool = False):
    """Try multiple ways to extract JSON from Gemini response."""
    # Newer SDKs may support .parsed when response_schema is provided
    try:
        return resp.parsed
    except Exception:
        pass
    # Try text field
    try:
        return json.loads(getattr(resp, 'text', ''))
    except Exception:
        pass
    # Try candidates -> parts
    try:
        cands = getattr(resp, 'candidates', None)
        if cands:
            for c in cands:
                parts = getattr(getattr(c, 'content', None), 'parts', [])
                for p in parts:
                    t = getattr(p, 'text', None)
                    if t:
                        return json.loads(t)
    except Exception:
        pass
    # Fallback
    return [] if expect_array else {}