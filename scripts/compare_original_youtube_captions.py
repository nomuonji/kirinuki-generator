"""Compare original YouTube caption bytes to existing RapidAPI candidate, no ASR.

This must only run after yt-dlp fetched real YouTube subtitle bytes into TMP.
Never claim authenticity from the RapidAPI response alone.
"""
import difflib
import hashlib
import html
import json
import os
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe_rapidapi import fetch_transcript_from_rapidapi_1, _normalize_segments

VIDEO_ID="4YSXNotY8QU"
tmp=Path(os.environ.get("CAPTION_TMP", "/tmp/annotated-world-yt-captions"))
files=sorted(
 x for x in tmp.glob("*")
 if x.is_file() and x.stat().st_size>500 and x.suffix.lower() in {".json3",".vtt"}
 and x.name.startswith(VIDEO_ID+".")
)
print("YOUTUBE_DIRECT_CAPTION_FILES_FOUND",len(files),flush=True)
if not files:
 print("YOUTUBE_DIRECT_CAPTION_ACQUIRED=0",flush=True)
 raise SystemExit(0)
source=next((x for x in files if x.suffix==".json3"),files[0])
blob=source.read_bytes()
print("YOUTUBE_DIRECT_CAPTION_ACQUIRED=1",flush=True)
print("YOUTUBE_DIRECT_CAPTION_NAME",source.name,flush=True)
print("YOUTUBE_DIRECT_CAPTION_BYTES",len(blob),flush=True)
print("YOUTUBE_DIRECT_CAPTION_SHA256",hashlib.sha256(blob).hexdigest(),flush=True)
if source.suffix==".json3":
 data=json.loads(blob)
 cues=[]
 for event in data.get("events",[]):
  text="".join(s.get("utf8","") for s in event.get("segs",[]))
  if text.strip():
   cues.append((float(event.get("tStartMs",0))/1000,html.unescape(text).strip()))
else:
 import re
 s=source.read_text(encoding="utf-8-sig")
 cues=[]
 for match in re.finditer(r"(\d\d:\d\d:\d\d\.\d+)\s+-->\s+[^\n]+\n([^\n]+)",s):
  ts=match.group(1)
  parts=ts.replace(".",":").split(":")
  start=int(parts[0])*3600+int(parts[1])*60+int(parts[2])+int(parts[3])/1000
  cues.append((start,html.unescape(re.sub(r"<[^>]+>","",match.group(2)))))
print("YOUTUBE_DIRECT_CUE_COUNT",len(cues),flush=True)
print("YOUTUBE_DIRECT_LAST_TIME",cues[-1][0] if cues else 0,flush=True)
if len(cues)<200 or cues[-1][0]<5000:
 raise SystemExit("Unusually incomplete original caption file")
# The original YouTube track must be present BEFORE a relay can count as comparable.
key=os.environ.get("RAPIDAPI_KEY")
if not key:
 print("RAPIDAPI_COMPARISON=skipped_key_missing",flush=True)
 raise SystemExit(0)
candidate=fetch_transcript_from_rapidapi_1(VIDEO_ID,key,"en")
if not candidate:
 print("RAPIDAPI_COMPARISON=failed",flush=True)
 raise SystemExit(0)
items=_normalize_segments(candidate)
normalize=lambda s:re.sub(r"\s+"," ",re.sub(r"[^a-z0-9']+"," ",html.unescape(s).lower())).strip()
scores=[]
for n in range(12):
 lo=n*5715/12
 hi=(n+1)*5715/12
 a=normalize(" ".join(t for start,t in cues if lo<=start<hi))
 b=normalize(" ".join(c["text"] for c in items if lo<=c["start"]<hi))
 if not a or not b:continue
 # compare blocks of <=1000 normalized characters near the center, avoiding
 # quadratic runtime on longer strings. Temporal windows may differ slightly.
 score=difflib.SequenceMatcher(None,a[:1000],b[:1000],autojunk=False).ratio()
 scores.append(round(score,3))
print("ORIGINAL_AND_RELAY_WINDOW_SIMILARITY",json.dumps(scores),flush=True)
print("ORIGINAL_RELAY_SIMILARITY_MEDIAN",sorted(scores)[len(scores)//2] if scores else 0,flush=True)
print("ORIGINAL_SUBTITLES_VERIFIED",int(bool(scores) and min(scores)>=0.6),flush=True)
# Never log or artifact source sentences; only hashes/aggregate scores.
