
from typing import List
import pathlib

def _fmt_time_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def clip_events_from_transcript(items: List[dict], start: float, end: float) -> List[dict]:
    """Return transcript segments overlapping [start,end], shifted so clip 0 is start."""
    out = []
    for it in items:
        s, e = float(it["start"]), float(it["end"])
        if e <= start or s >= end:
            continue
        s_clip = max(0.0, s - start)
        e_clip = max(0.0, e - start)
        out.append({"start": s_clip, "end": e_clip, "text": it["text"]})
    return out

def write_srt(events: List[dict], path: pathlib.Path) -> None:
    lines = []
    for i, ev in enumerate(events, start=1):
        lines.append(str(i))
        lines.append(f"{_fmt_time_srt(ev['start'])} --> {_fmt_time_srt(ev['end'])}")
        lines.append(str(ev["text"]).strip())
        lines.append("")  # blank line
    path.write_text("\n".join(lines), encoding="utf-8")

ASS_HEADER = "; Script generated\n[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.601\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Sub, Noto Sans JP, 52, &H00FFFFFF, &H000000FF, &H00000000, &H64000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 3, 0, 2, 60, 60, 180, 1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

def _fmt_time_ass(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))  # centiseconds
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def write_ass(events: List[dict], path: pathlib.Path) -> None:
    lines = [ASS_HEADER]
    for ev in events:
        start = _fmt_time_ass(ev["start"])
        end = _fmt_time_ass(ev["end"])
        text = str(ev["text"]).replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{start},{end},Sub,,0,0,0,,{text}")
    path.write_text("\n".join(lines), encoding="utf-8")
