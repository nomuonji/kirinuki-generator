"""One-shot source-cue sampling for the Annotated World. NOT a transcript exporter.

Reads the existing RapidAPI caption candidate under an existing Repository Secret
on a trusted main-branch GitHub Actions push. Logs only bounded, short candidate
snippets and analytic counts. Never writes raw transcript to Git/artifacts/logs.
"""
import collections
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe_rapidapi import fetch_transcript_from_rapidapi_1, _normalize_segments

VIDEO_ID = "4YSXNotY8QU"
KNOWN_DURATION = 5715
assert re.fullmatch(r"[A-Za-z0-9_-]{11}", VIDEO_ID)
key = os.environ.get("RAPIDAPI_KEY", "")
if not key:
    raise SystemExit("RAPIDAPI_KEY secret not configured; no source evidence available")
raw = fetch_transcript_from_rapidapi_1(VIDEO_ID,key,"en")
if not isinstance(raw,list) or not raw:
    raise SystemExit("RapidAPI returned no usable caption candidates")
items = _normalize_segments(raw)
if len(items) < 300 or max(x["end"] for x in items) < 5100:
    raise SystemExit("Caption response insufficient for 95min source")
if any(x["start"] < 0 or x["end"] <= x["start"] or x["start"] > KNOWN_DURATION + 10 for x in items):
    raise SystemExit("Invalid caption timestamps")
if any(items[n]["start"] > items[n+1]["start"] for n in range(len(items)-1)):
    raise SystemExit("Unsorted captions")
blob = json.dumps(items,ensure_ascii=False,sort_keys=True).encode("utf-8")
print("CANDIDATE_SOURCE_ID",VIDEO_ID,flush=True)
print("CANDIDATE_SOURCE_METHOD","rapidapi1_existing_captions",flush=True)
print("CANDIDATE_COUNT",len(items),flush=True)
print("CANDIDATE_DURATION",round(items[-1]["end"],3),flush=True)
print("CANDIDATE_SHA256",hashlib.sha256(blob).hexdigest(),flush=True)
print("CANDIDATE_CAPTURED_UTC",datetime.datetime.now(datetime.timezone.utc).isoformat(),flush=True)
print("CANDIDATE_RAW_SCHEMA",sorted(str(k) for k in raw[0].keys()) if isinstance(raw[0],dict) else type(raw[0]).__name__,flush=True)
print("CANDIDATE_ORIGIN_VERIFIED",False,flush=True)
# Analysis may show English content or a provider language mismatch, but does
# not by itself verify YouTube's original caption track.
words=re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
stop={"you","the","that","and","for","with","are","but","can","have","this","from","what","they","your","not","like","will","about","because","those","them","there","it's","just","let","were","would","could","then","been","which","don't","our","when","into","some","people","think","know","really","actually","said","very","here","now"}
themes=["freedom","free","liberty","choice","necessity","change","rules","past","history","hegel","love","film","coffee","capitalism","neofeudal","technofeudal","russia","ukraine","war","poetry","identity","religion","politics","ideology","knowledge","truth","democracy","charity","ecology","climate","life","language","death"]
length=items[-1]["end"]
for n in range(12):
    low=length*n/12
    high=length*(n+1)/12
    block=[x for x in items if low<=x["start"]<high]
    freq=collections.Counter(y.lower() for x in block for y in words.findall(x["text"]))
    topics={t:freq[t] for t in themes if freq[t]}
    top=sorted(topics.items(),key=lambda x:-x[1])[:8]
    # select a mid-window cue, enough to identify a topic but not publish
    # a full block of third-party-processed transcript.
    candidates=[x for x in block if 30<=len(x["text"])<=150 and len(words.findall(x["text"]))>=6]
    mid=(low+high)/2
    target=min(candidates,key=lambda x:abs(x["start"]-mid)) if candidates else (block[0] if block else None)
    excerpt=""
    stamp=None
    if target:
        excerpt=" ".join(target["text"].split())
        excerpt=" ".join(excerpt.split()[:11])
        stamp=round(target["start"],2)
    print("CANDIDATE_WINDOW",json.dumps({
      "index":n+1,"start":int(low),"end":int(high),"count":len(block),
      "topics":top,"sampleTime":stamp,"shortCandidateQuote":excerpt,
      "warning":"UNVERIFIED_YOUTUBE_CAPTION_ORIGIN"
    },ensure_ascii=False),flush=True)
print("CANDIDATE_WORDS_TOTAL",sum(len(words.findall(x["text"])) for x in items),flush=True)
print("CANDIDATE_NON_LATIN_RATIO",round(sum(1 for x in items for c in x["text"] if ord(c)>127)/max(1,sum(len(x["text"]) for x in items)),4),flush=True)
print("CANDIDATE_PROVENANCE_GATE","OPEN",flush=True)
