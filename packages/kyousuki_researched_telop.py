"""Today's Suki title-free telop, based on docs/design/README.md (2026-11-18).

The original research called for: black canvas, two-tone outlined editorial hook,
highlighted words, the full-width scene, spoken text over the clip edge, and an
editorial punchline below.  A repost's sourceVideoTitle is never an input here.

Keep this renderer independent of the standard Remotion bundles for the faster
FFmpeg source-episode stock migration; same editorial zones, no title kicker.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

# BGR is libass's required hexadecimal color order.
VARIANTS = (
    {"a": ("#FFFFFF", "#FF2E7E"), "b": ("#FF2E7E", "#FFFFFF"),
     "hl": ("#FFE94A", "#111111"), "punch": ("#FF2E7E", "#FFFFFF")},
    {"a": ("#FFFFFF", "#111111"), "b": ("#E8132B", "#FFFFFF"),
     "hl": ("#FFE600", "#111111"), "punch": ("#E8132B", "#FFFFFF")},
    {"a": ("#B45CFF", "#FFFFFF"), "b": ("#FF5FA8", "#FFFFFF"),
     "hl": ("#FF5FA8", "#111111"), "punch": ("#FFFFFF", "#B45CFF")},
)

def telop_design(episode_key, clip_index):
    """Replay the existing researched LRU rotation, never a fixed A→B→C loop.

    The v1 stock incorrectly stored variant=1 for every one of 23 clips.
    Save that as legacy evidence, and derive a stable design from the common
    design_rotation.py generator and the canonical episode order.
    """
    from packages.design_rotation import pick_designs
    ep=int(str(episode_key).rsplit(":",1)[-1])
    offsets={2:0,3:6,4:12,5:17}
    index=int(clip_index)
    maximum={2:6,3:6,4:5,5:6}
    if ep not in offsets or not 1<=index<=maximum[ep]:
        raise ValueError("Unexpected canonical episode/clip for stock rotation")
    position=offsets[ep]+index-1
    return pick_designs([],23,seed="kyousuki-suwon-2026-v6",
                        pool=("telop",))[position]


def telop_variant(episode_key, clip_index):
    return telop_design(episode_key,clip_index)["variant"]


def ass_color(css):
    rgb=css.lstrip("#")
    if not re.fullmatch(r"[a-fA-F0-9]{6}",rgb):
        raise ValueError("Invalid design ink")
    return "&H"+rgb[4:6]+rgb[2:4]+rgb[0:2]+"&"

def escape_ass(s):
    return s.replace("\\","＼").replace("{","（").replace("}","）").replace("\r","").replace("\n",r"\N")

def segments(text):
    """Inline **highlight** segments, preserving Japanese words for wrapping."""
    if not isinstance(text,str) or not text.strip():
        raise ValueError("Missing authored hook/punchline")
    chunks=re.split(r"(\*\*[^*]+\*\*)",text.strip())
    chars=[]
    for part in chunks:
        highlighted=part.startswith("**") and part.endswith("**")
        plain=part[2:-2] if highlighted else part.replace("**","")
        chars.extend((char,highlighted) for char in plain)
    if not chars or len(chars)>100:
        raise ValueError("Empty or oversized rich label")
    return chars

def break_rich(text, *, max_width=920, max_lines=2, preferred_size=80, min_size=44):
    chars=segments(text)
    # Japanese glyphs occupy one em; ASCII and punctuation are narrower.
    units=[0.55 if ord(c)<0x2e80 else 1 for c,_ in chars]
    total=sum(units)
    font=min(preferred_size,max(min_size,int(max_width/(total+1)))) if total<=13 else min(70,max(min_size,int(max_width/(total/max_lines+1))))
    capacity=max_width/font
    lines=[]
    line=[]
    used=0
    for i,part in enumerate(chars):
        unit=units[i]
        if line and used+unit>capacity:
            lines.append(line)
            line=[]
            used=0
        line.append(part)
        used+=unit
    if line:lines.append(line)
    if len(lines)>max_lines:
        raise ValueError("Editorial text cannot fit two lines")
    return lines,font

def rich_ass(lines,palette):
    """Alternate researched headline inks line-to-line; highlights use third ink."""
    chunks=[]
    for i,line in enumerate(lines):
        normal=palette["a" if i%2==0 else "b"]
        last=None
        for char,highlighted in line:
            ink=palette["hl"] if highlighted else normal
            if ink!=last:
                chunks.append(r"{\1c"+ass_color(ink[0])+r"\3c"+ass_color(ink[1])+"}")
                last=ink
            chunks.append(escape_ass(char))
        if i<len(lines)-1:chunks.append(r"\N")
    return "".join(chunks)

def ass_time(seconds):
    centiseconds=max(0,round(seconds*100))
    hrs,rem=divmod(centiseconds,360000)
    mins,rem=divmod(rem,6000)
    sec,cs=divmod(rem,100)
    return f"{hrs}:{mins:02}:{sec:02}.{cs:02}"

def spoken_caption(text):
    """Return 1–4 spoken lines; never truncate, change text or move timestamps."""
    if not isinstance(text,str):return ""
    text=text.strip()
    if not text:return ""
    n=len(text)
    size,limit=(58,16) if n<=16 else (52,17) if n<=34 else (46,20) if n<=55 else (40,23)
    pieces=[]
    while text:
        if len(text)<=limit:
            pieces.append(text)
            break
        boundary=limit
        if text[limit] in "、。！？!?.,)」』":
            boundary+=1
        else:
            for at in range(limit-1,max(9,limit-5),-1):
                if text[at-1] in "、。！？!?":
                    boundary=at
                    break
        pieces.append(text[:boundary])
        text=text[boundary:]
    if len(pieces)>4:
        raise ValueError("Subtitle is too long for 9:16 safe zone")
    return r"{\fs"+str(size)+"}"+r"\N".join(escape_ass(part) for part in pieces)

def render_ass(*, subtitles, seconds, output, hook, punchline, video_top,
               video_height, variant=0, fps=30, reactions=None):
    """Return rendered dialogue count and layout receipt; no source title allowed."""
    video_bottom=video_top+video_height
    if not 0<video_top<video_bottom<1600:
        raise ValueError("Source video geometry is invalid")
    if not isinstance(variant,int): variant=0
    palette=VARIANTS[variant%len(VARIANTS)]
    hlines,hsize=break_rich(hook)
    plines,psize=break_rich(punchline,preferred_size=76,min_size=42)
    hook_y=video_top-22
    punch_y=video_bottom+50
    sub_bottom=video_bottom-20
    if hook_y-len(hlines)*hsize*1.27<110 or punch_y+len(plines)*psize*1.2>1615:
        raise ValueError("Headline/punchline would leave YouTube Shorts safe bounds")
    header=(
      "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
      "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
      "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
      "Style: Hook,Noto Sans CJK JP,80,&H00FFFFFF,&H00FFFFFF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,7,2,2,64,140,0,1\n"
      "Style: Speech,Noto Sans CJK JP,58,&H00FFFFFF,&H00FFFFFF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,5,2,2,64,140,0,1\n"
      "Style: Punch,Noto Sans CJK JP,76,&H00FFFFFF,&H00FFFFFF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,6,2,8,64,140,0,1\n"
      "Style: Reaction,Noto Sans CJK JP,53,&H0000E9FF,&H0000E9FF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,5,2,7,64,140,0,1\n"
      "Style: EditorComment,Noto Sans CJK JP,46,&H00FFFFFF,&H00FFFFFF,&H99141414,&H88141414,-1,0,0,0,100,100,0,0,3,16,0,7,64,140,0,1\n\n"
      "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    top_label=r"{\an2\pos(540,"+str(hook_y)+r")\fs"+str(hsize)+"}"+rich_ass(hlines,palette)
    bottom_label=r"{\an8\pos(540,"+str(punch_y)+r")\fs"+str(psize)+"}"+rich_ass(plines,
        {"a":palette["punch"],"b":palette["punch"],"hl":palette["hl"]})
    rows=[
      f"Dialogue: 0,0:00:00.00,{ass_time(seconds)},Hook,,0,0,0,,{top_label}",
      f"Dialogue: 0,0:00:00.00,{ass_time(seconds)},Punch,,0,0,0,,{bottom_label}",
    ]
    count=0
    for sub in subtitles:
        try:
            first=float(sub["startFrame"])/fps
            last=min(float(sub["endFrame"])/fps,seconds-0.03)
        except (KeyError,TypeError,ValueError):continue
        if first<0 or last<=first:continue
        line=spoken_caption(sub.get("text"))
        if not line:continue
        at=r"{\an2\pos(540,"+str(sub_bottom)+")}"
        rows.append(f"Dialogue: 1,{ass_time(first)},{ass_time(last)},Speech,,0,0,0,,{at+line}")
        count+=1
    for reaction in reactions or []:
        try:
            start=max(0,int(reaction["startFrame"]))/fps
            stop=min(seconds,(int(reaction["startFrame"])+int(reaction["durationInFrames"]))/fps)
        except (KeyError,TypeError,ValueError):
            continue
        if stop<=start:continue
        text=escape_ass(str(reaction.get("text") or "").strip())
        if not text:continue
        if len(text)>18:raise ValueError("Reaction cut-in is too long")
        editorial=reaction.get("emotion")=="editorial"
        if editorial:
            # An explicit editorial label: never impersonate real viewer comments.
            at=r"{\an7\pos(65,"+str(video_top+45)+r")\fad(100,150)}"
            text=escape_ass("編集コメント  ")+text
            style="EditorComment"
        else:
            at=r"{\an7\pos(65,"+str(video_top+100)+")}"
            style="Reaction"
        rows.append(f"Dialogue: 2,{ass_time(start)},{ass_time(stop)},{style},,0,0,0,,{at+text}")
    if count==0:raise ValueError("No real spoken caption events")
    Path(output).write_text(header+"\n".join(rows)+"\n",encoding="utf-8")
    return {
       "subtitleCount":count,"videoTop":video_top,"videoBottom":video_bottom,
       "hook":" ".join("".join(c for c,_ in l) for l in hlines),
       "punchline":" ".join("".join(c for c,_ in l) for l in plines),
       "hookRows":len(hlines),"punchRows":len(plines),
       "template":"telop","variant":variant%len(VARIANTS),
       "deadSpaceTreatment":"dark_source_blur",
       "sourceTitleComposited":False,"spokenCaptionBottom":sub_bottom
    }
