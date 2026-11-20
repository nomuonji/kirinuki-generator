"""Compare existing YouTube captions from two independently operated RapidAPI relays.

No local ASR. No public transcript. Agreement is NOT proof that either payload
is YouTube's authoritative subtitle track; do not mark direct capture verified.
"""
import collections
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transcribe_rapidapi import (
 fetch_transcript_from_rapidapi_1,
 fetch_transcript_from_rapidapi_2,
 _normalize_segments
)
VIDEO="4YSXNotY8QU"
key=os.environ.get("RAPIDAPI_KEY","")
if not key:
 raise SystemExit("Missing existing RAPIDAPI_KEY secret")
a=fetch_transcript_from_rapidapi_1(VIDEO,key,"en")
b=fetch_transcript_from_rapidapi_2(VIDEO,key)
if not a:
 print("RELAY1_AVAILABLE=0",flush=True)
 raise SystemExit(0)
aa=_normalize_segments(a)
print("RELAY1_AVAILABLE=1",flush=True)
print("RELAY1_COUNT",len(aa),flush=True)
print("RELAY1_LAST",max(x["end"] for x in aa),flush=True)
print("RELAY1_SHA256",hashlib.sha256(json.dumps(aa,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),flush=True)
if not b:
 print("RELAY2_AVAILABLE=0",flush=True)
 print("INDEPENDENT_PROVIDER_AGREEMENT=unavailable",flush=True)
 raise SystemExit(0)
bb=_normalize_segments(b)
print("RELAY2_AVAILABLE=1",flush=True)
print("RELAY2_COUNT",len(bb),flush=True)
print("RELAY2_LAST",max(x["end"] for x in bb),flush=True)
print("RELAY2_SHA256",hashlib.sha256(json.dumps(bb,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),flush=True)
def tokens(text):
 return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?",html.unescape(text.lower()))
scores=[]
for k in range(12):
 low=5715*k/12
 high=5715*(k+1)/12
 at=tokens(" ".join(x["text"] for x in aa if low<=x["start"]<high))
 bt=tokens(" ".join(x["text"] for x in bb if low<=x["start"]<high))
 ac=collections.Counter(at)
 bc=collections.Counter(bt)
 overlap=sum((ac&bc).values())
 denom=max(1,sum((ac|bc).values()))
 score=round(overlap/denom,4)
 scores.append(score)
 print("RELAY_AGREEMENT_WINDOW",k+1,score,"wordCounts",len(at),len(bt),flush=True)
print("RELAY_AGREEMENT_AVG",round(sum(scores)/len(scores),4),flush=True)
print("RELAY_AGREEMENT_MIN",min(scores),flush=True)
print("RELAY_AGREEMENT_HIGH",int(min(scores)>0.82),flush=True)
print("YOUTUBE_AUTHORITATIVE_TRACK_CONFIRMED=0",flush=True)
