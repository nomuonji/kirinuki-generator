import os, json, time, re
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

def _strip_markup(text: str) -> str:
    """Remove **markers** and collapse whitespace for plain storage."""
    if not text:
        return ""
    plain = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    plain = plain.replace("\r\n", "\n").replace("\r", "\n")
    plain = plain.replace("\n", " ")
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain

def _sanitize_plain_text(candidate: str, fallback: str = "") -> str:
    base = candidate if candidate else fallback
    return _strip_markup(base)

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

def propose_clips_from_transcript(items: List[dict], preset="shorts", min_gap=30.0, min_sec=30.0, max_sec=120.0, concept: str = "") -> List[ClipCandidate]:
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

    concept_prompt = f"**Video Concept:**\n{concept}\n\n" if concept else ""
    sys = f"""{concept_prompt}You are a master video editor, specializing in creating viral short-form content. Your task is to analyze a timestamped transcript and identify the most compelling, self-contained clips.

**Your Goal:** Propose clips that are high-impact and feel complete.

**Key Principles:**
1.  **Content Awareness:** Read the surrounding context carefully. Track topic boundaries and speaker identities so you never cut a clip while a thought or exchange is still unfolding.
2.  **Pacing and Flow:** Each clip must represent a complete thematic unit. It should not feel like it's cut off abruptly, even if the smoothest boundary lands slightly outside the duration target.
3.  **Speaker & Context Boundaries:** Ideal boundaries occur when a speaker concludes their point, a new topic or speaker begins, or there is a natural pause. Never break in the middle of a punchline or key explanation.
4.  **Length Guidance:** Aim for clips that feel perfectly timed around 30-120 seconds. Prioritize a clean conversational break over rigid timing, and go shorter/longer only when it keeps the story intact.
5.  **Natural Endings:** Prioritize ending on transcript segments that finish a sentence or idea, are followed by a noticeable pause, or clearly close a conversational beat.
6.  **AVOID:** Do not end on conjunctions, filler, or before a reveal lands.

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
    upper: str = Field(..., description="Plain text for the top of the video (no markup).")
    lower: str = Field(..., description="Plain text for the bottom of the video (no markup).")
    upper_decorated: str = Field("", description="Decorated rich text for the top (youth slang with **highlight** markup and optional line breaks).")
    lower_decorated: str = Field("", description="Decorated rich text for the bottom (youth slang with **highlight** markup and optional line breaks).")

def generate_hook_text(clip_transcript: str) -> HookText:
    """
    Generates catchy hook texts for a video clip based on its transcript.
    """
    from google.generativeai import protos

    hook_schema = protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "upperDecorated": protos.Schema(type=protos.Type.STRING),
            "lowerDecorated": protos.Schema(type=protos.Type.STRING),
            "upperPlain": protos.Schema(type=protos.Type.STRING),
            "lowerPlain": protos.Schema(type=protos.Type.STRING),
        },
        required=["upperDecorated", "lowerDecorated"],
    )

    sys = (
        "You are a viral video producer crafting overlay text for short-form clips. "
        "Write in energetic Japanese youth slang. Follow these formatting rules strictly: "
        "1) Provide decorated text using **double asterisks** around up to three key phrases that must pop. "
        "2) Use \\n (newline) to break the copy into at most two short lines that read naturally. "
        "3) Avoid any markup besides the **emphasis** markers. No emojis that break encoding. "
        "4) Also supply a plain version with no markup, replacing newlines by spaces, for metadata storage. "
        "Return JSON with fields upperDecorated, lowerDecorated, upperPlain, lowerPlain."
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
    upper_decorated = str(parsed.get("upperDecorated", ""))
    lower_decorated = str(parsed.get("lowerDecorated", ""))
    upper_plain = _sanitize_plain_text(str(parsed.get("upperPlain", "")), upper_decorated)
    lower_plain = _sanitize_plain_text(str(parsed.get("lowerPlain", "")), lower_decorated)
    return HookText(
        upper=upper_plain,
        lower=lower_plain,
        upper_decorated=upper_decorated,
        lower_decorated=lower_decorated,
    )


def generate_hooks_bulk(clip_items: List[Dict], concept: str = "") -> Dict[int, HookText]:
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
                "upperDecorated": protos.Schema(type=protos.Type.STRING),
                "lowerDecorated": protos.Schema(type=protos.Type.STRING),
                "upperPlain": protos.Schema(type=protos.Type.STRING),
                "lowerPlain": protos.Schema(type=protos.Type.STRING),
            },
            required=["index", "upperDecorated", "lowerDecorated"],
        ),
    )

    concept_prompt = f"The overall concept of the video is: {concept}. " if concept else ""
    sys = (
        f"You are a viral video producer. {concept_prompt}For each item, craft youth-slang overlay text for the top and bottom bands."
        "Follow the same formatting rules for decorated text as above (wrap highlights with **, use at most two lines separated by \n, and avoid other markup)."
        "Always include plain copies with markup removed so they can be stored safely."
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
            upper_decorated = str(obj.get("upperDecorated", ""))
            lower_decorated = str(obj.get("lowerDecorated", ""))
            upper_plain = _sanitize_plain_text(str(obj.get("upperPlain", "")), upper_decorated)
            lower_plain = _sanitize_plain_text(str(obj.get("lowerPlain", "")), lower_decorated)
            out[idx] = HookText(
                upper=upper_plain,
                lower=lower_plain,
                upper_decorated=upper_decorated,
                lower_decorated=lower_decorated,
            )
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