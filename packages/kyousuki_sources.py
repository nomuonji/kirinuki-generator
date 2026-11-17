"""Scheduled Kyousuki metadata discovery; account hints are not licensing evidence."""
from __future__ import annotations
import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / "configs/kyousuki_sources.json"
BVID = re.compile(r"BV[A-Za-z0-9]{10}")
FULL_EP = re.compile(r"(?:篇|编|編)\s*[\]】）)]?\s*(?:第\s*)?(?:EP\s*|#\s*)?([0-9]{1,2}|[一二三四五六七八九十]+)\s*(?:话|話|回)?", re.I)
EXTRAS = re.compile(r"预告|予告|片段|切り抜き|花絮|反应|reaction|直播|shorts?|part\s*\d|分割|番外|合集|合集",re.I)
YEAR = re.compile(r"20[2-3]\d")
SEASON = re.compile(r"([\w\u3400-\u9fff\u3040-\u30ff]{2,18}?)(?:篇|编|編)")
ALIASES={"韩国水原":"スウォン","水原":"スウォン","スウォン":"スウォン","仁川":"仁川","インチョン":"仁川","马克坦岛":"マクタン","马克坦":"マクタン","マクタン":"マクタン"}
NUM=dict(zip("一二三四五六七八九十", range(1,11)))


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _clean(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def _duration(value):
    try:
        parts=[int(p) for p in str(value).split(":")]
        if not 1 <= len(parts) <= 3 or any(p<0 for p in parts):
            return 0
        total=0
        for p in parts: total=60*total+p
        return total
    except (TypeError, ValueError):
        return 0


def episode_key(title):
    """Conservative grouping: unknown year/season or ambiguous titles remain unresolved."""
    title=_clean(title)
    y=YEAR.search(title)
    n=FULL_EP.search(title)
    if not (y and n) or EXTRAS.search(title):
        return None
    preceding=title[:n.start()]
    aliases=sorted(ALIASES,key=len,reverse=True)
    season=next((ALIASES[k] for k in aliases if preceding.endswith(k)),None)
    if not season:
        # Unfamiliar season names need official episode matching, not guessed equivalence.
        return None
    num=n.group(1)
    ep=int(num) if num.isdigit() else NUM.get(num)
    if not ep or not 1<=ep<=20:
        return None
    return f"{y.group()}:{season}:{ep}"


def normalize(row, account, now):
    bid=str(row.get("bvid") or "")
    title=_clean(row.get("title"))
    author=_clean(row.get("author"))
    mid=str(row.get("mid") or "")
    if (not BVID.fullmatch(bid) or author!=account["name"] or not mid.isdigit()
            or (account.get("mid") is not None and str(account["mid"])!=mid)):
        return None
    dur=_duration(row.get("duration"))
    if dur<18*60 or dur>150*60 or EXTRAS.search(title):
        return None
    try: posted=datetime.fromtimestamp(int(row.get("pubdate")),tz=timezone.utc)
    except (TypeError,ValueError,OSError,OverflowError): return None
    age=(now-posted).total_seconds()/86400
    if not 0<=age<=90:
        return None
    return {"bvid":bid,"title":title,"author":author,"mid":mid,"durationSeconds":dur,
            "publishedAt":posted.isoformat(),"priority":account["priority"],
            "episodeKey":episode_key(title),"approvalStatus":"metadata_only"}


def search(keyword, timeout=12):
    # Public metadata search only. No cookie harvesting, WBI spoofing, proxy, or retry on denial.
    url="https://api.bilibili.com/x/web-interface/search/type?"+urllib.parse.urlencode({
        "search_type":"video","keyword":keyword,"order":"pubdate","page":1})
    request=urllib.request.Request(url,headers={"Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        data=json.loads(response.read(2_000_001))
    if data.get("code")!=0: raise RuntimeError("public API returned nonzero code")
    rows=(data.get("data") or {}).get("result") or []
    if not isinstance(rows,list): raise ValueError("Unexpected search shape")
    return rows


def discover(reg=None, fetch=search, now=None):
    reg=reg or load_registry()
    now=now or datetime.now(timezone.utc)
    names={a["name"]:a for a in reg["accounts"]}
    rows={}
    diagnostics=[]
    for kw in reg["searchKeywords"]:
        try:
            result=fetch(kw)
            diagnostics.append({"keyword":kw,"status":"ok","rows":len(result)})
        except Exception as exc:
            # A denied request is not silently classified as no new episodes.
            diagnostics.append({"keyword":kw,"status":"failed","error":type(exc).__name__,
                                "httpStatus":getattr(exc,"code",None)})
            if getattr(exc,"code",None) in (401,403,412,429):
                break
            continue
        for row in result:
            if not isinstance(row,dict): continue
            account=names.get(_clean(row.get("author")))
            if account:
                normalized=normalize(row,account,now)
                if normalized: rows[normalized["bvid"]]=normalized
    candidates=sorted(rows.values(),key=lambda c:(-datetime.fromisoformat(c["publishedAt"]).timestamp(),c["priority"],c["bvid"]))
    groups={}
    for c in candidates:
        key=c["episodeKey"] or "unresolved:"+c["bvid"]
        groups.setdefault(key,[]).append(c)
    for members in groups.values():
        members.sort(key=lambda c:(c["priority"],-datetime.fromisoformat(c["publishedAt"]).timestamp(),c["bvid"]))
    return {"checkedAt":now.isoformat(),"status":"ok" if diagnostics and all(d["status"]=="ok" for d in diagnostics) else "degraded",
            "accounts":reg["accounts"],"diagnostics":diagnostics,"episodeGroups":groups,
            "candidateCount":len(candidates),"approvedSourceCount":len(reg["approvedSources"]),
            "autoAcquisitionAuthorized":False,"reason":"discovery metadata is not source or publication authorization"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    data=discover()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("KYOUSUKI_DISCOVERY",json.dumps({"status":data["status"],"candidates":data["candidateCount"],
         "approved":data["approvedSourceCount"],"diagnostics":data["diagnostics"]},ensure_ascii=False))


if __name__=="__main__":
    main()
