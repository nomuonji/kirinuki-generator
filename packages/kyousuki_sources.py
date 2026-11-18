"""Scheduled Kyousuki metadata discovery; account hints are not licensing evidence."""
from __future__ import annotations
import argparse
import html
import json
import os
import re
import urllib.error
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
    config=json.loads(REGISTRY.read_text(encoding="utf-8"))
    raw=os.environ.get("KYOUSUKI_APPROVALS_JSON","").strip()
    if raw:
        try:
            entries=json.loads(raw)
            if not isinstance(entries,list): raise ValueError("Expected a list")
            config["approvedSources"]=entries
        except (ValueError,TypeError):
            config["approvedSources"]=[]
            print("KYOUSUKI_APPROVALS_INVALID: production disabled")
    return config


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


def approval_records(reg=None):
    """Explicit per-source permission records, never a discovery-name allowlist."""
    reg=reg or load_registry()
    accepted=[]
    for record in reg.get("approvedSources",[]):
        if not isinstance(record,dict): continue
        bvid=str(record.get("bvid",""))
        if not BVID.fullmatch(bvid): continue
        if type(record.get("page")) is not int or record["page"] < 1: continue
        if not str(record.get("mid","")).isdigit(): continue
        if not any(a["name"]==record.get("author") and
                   (a.get("mid") is None or str(a["mid"])==str(record["mid"]))
                   for a in reg["accounts"]): continue
        if str(record.get("officialYoutubeVideoId","")) and not re.fullmatch(r"[A-Za-z0-9_-]{11}",record["officialYoutubeVideoId"]): continue
        if not re.fullmatch(r"20[2-3]\d:[^:\r\n]{1,32}:[1-9]\d?",str(record.get("episodeKey",""))): continue
        if not re.fullmatch(r"https://abema\.tv/video/episode/[A-Za-z0-9_-]+",str(record.get("officialEpisodeUrl",""))): continue
        if not isinstance(record.get("rightsEvidence"),str) or not record["rightsEvidence"].strip(): continue
        if record.get("processingAuthorized") is not True or record.get("publicationAuthorized") is not True: continue
        if not isinstance(record.get("stockFolderId"),str) or not record["stockFolderId"]: continue
        accepted.append(record)
    return accepted


def approved_source(bvid,page,folder,reg=None):
    rows=[r for r in approval_records(reg) if r["bvid"]==bvid and r["page"]==page and r["stockFolderId"]==folder]
    if len(rows)!=1:
        raise ValueError("No unambiguous, documented Bilibili source and posting-stock authorization")
    return rows[0]


def approved_candidates(discovery, processed_entries, folder, now=None, reg=None, max_age_days=90):
    """Choose one approved provider per episode. No rollover after partial stock creation.

    Failures use provider-specific state keys. Completed episodes / completed official
    source aliases suppress every mirror. Source grants, not untrusted metadata, own
    canonical episode identity and date. If live discovery fails, known explicitly
    approved rows remain eligible; a newly discovered unapproved row never is.
    """
    now=now or datetime.now(timezone.utc)
    known={c["bvid"]:c for g in discovery.get("episodeGroups",{}).values() for c in g}
    records=approval_records(reg)
    groups={}
    for r in records:
        if r["stockFolderId"]!=folder:
            continue
        try:
            aired=datetime.fromisoformat(r["officialPublishedAt"].replace("Z","+00:00"))
            age=(now-aired).total_seconds()/86400
            dur=int(r["durationSeconds"])
        except (ValueError,TypeError,KeyError): continue
        if not 0<=age<=max_age_days or not 1080<=dur<=9000: continue
        if not isinstance(r.get("title"),str) or not r["title"].strip(): continue
        live=known.get(r["bvid"])
        if live and (live["mid"]!=str(r["mid"]) or live["author"]!=r["author"]): continue
        sid=f'bilibili_{r["bvid"]}_p{r["page"]}_auto'
        byid={p.get("videoId"):p for p in processed_entries}
        if byid.get(r.get("officialYoutubeVideoId"),{}).get("status")=="completed": continue
        related=[p for p in processed_entries if p.get("episodeKey")==r["episodeKey"] or
                 p.get("videoId") in {sid,r.get("officialYoutubeVideoId")}]
        if any(p.get("status")=="completed" or (p.get("videoId")!=sid and int(p.get("uploadedClips") or 0)>0) for p in related): continue
        prior=byid.get(sid,{})
        if int(prior.get("attempts") or 0)>=3: continue
        if prior.get("processedAt"):
            try:
                elapsed=(now-datetime.fromisoformat(prior["processedAt"].replace("Z","+00:00"))).total_seconds()
                if elapsed<21600: continue
            except ValueError: continue
        priority=next(a["priority"] for a in (reg or load_registry())["accounts"] if a["name"]==r["author"])
        groups.setdefault(r["episodeKey"],[]).append({"videoId":sid,"sourcePlatform":"bilibili","bvid":r["bvid"],"page":r["page"],
            "episodeKey":r["episodeKey"],"officialYoutubeVideoId":r.get("officialYoutubeVideoId"),"title":r["title"],
            "publishedAt":aired.isoformat(),"ageHours":age*24,"durationSeconds":dur,
            "selectionScore":0.82 if age<=1 else 0.65,"viewsPerHour":0.0,"views":0,"likes":0,"comments":0,"priority":priority})
    # Newer episodes first; alternate providers in priority order. Caller must
    # recheck durable state/partial uploads before attempting another provider.
    return sorted((c for g in groups.values() for c in g),
                  key=lambda c:(-datetime.fromisoformat(c["publishedAt"]).timestamp(),c["priority"],c["videoId"]))


# Public metadata only. Use account archives, never keyword search.
# No synthetic WBI signatures, cookies, proxies or fallback after denial.
DENIAL_CODES = {401, 403, 412, 429, -101, -352, -403, -412, -509}
PROGRAMME_TITLE = re.compile(r"今天[、，,\s]*喜欢上你了|今天[、，,\s]*喜欢你了|今喜|今日好き|今日[、，,\s]*好きになりました|今日[、，,\s]*好き", re.I)


class MetadataResponseError(RuntimeError):
    def __init__(self, code):
        super().__init__("Bilibili returned a nonzero metadata code")
        self.code = code


def public_metadata(path, params, timeout=12):
    url = "https://api.bilibili.com" + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(2_000_001))
    if data.get("code") != 0:
        raise MetadataResponseError(data.get("code"))
    if not isinstance(data.get("data"), dict):
        raise ValueError("Unexpected metadata response")
    return data["data"]


def resolve_account(account):
    """Resolve an unknown MID from the already marked exact reference video."""
    bvid = str(account.get("referenceBvid") or "")
    if not BVID.fullmatch(bvid):
        raise ValueError("Missing reference video")
    data = public_metadata("/x/web-interface/view", {"bvid": bvid})
    owner = data.get("owner") or {}
    mid = str(owner.get("mid") or "")
    if data.get("bvid") != bvid or _clean(owner.get("name")) != account["name"] or not mid.isdigit():
        raise ValueError("Reference uploader identity mismatch")
    return mid


def account_uploads(account):
    """Read the newest public archive page by MID, without keyword parameters."""
    mid = str(account.get("mid") or "")
    if not mid.isdigit():
        raise ValueError("Missing account MID")
    data = public_metadata("/x/space/wbi/arc/search", {
        "mid": mid, "pn": 1, "ps": 30, "order": "pubdate"
    })
    rows = (data.get("list") or {}).get("vlist")
    if not isinstance(rows, list):
        raise ValueError("Unexpected account archive shape")
    if rows and not any(isinstance(row,dict) and str(row.get("mid") or "") == mid
                        and _clean(row.get("author")) == account["name"] for row in rows):
        raise ValueError("Archive uploader identity mismatch")
    mapped = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("mid") or "") != mid or _clean(row.get("author")) != account["name"]:
            continue
        if not PROGRAMME_TITLE.search(_clean(row.get("title"))):
            continue
        mapped.append({**row, "duration": row.get("length"), "pubdate": row.get("created")})
    return mapped


def discover(reg=None, fetch=account_uploads, now=None, resolve=resolve_account):
    reg=reg or load_registry()
    now=now or datetime.now(timezone.utc)
    rows={}
    diagnostics=[]
    accounts=sorted(reg["accounts"], key=lambda a:a["priority"])
    # Verify the account-list path first using configured IDs. Unknown IDs are
    # resolved from exact reference videos only after accessible list checks.
    ordered=sorted(accounts, key=lambda a:(not bool(a.get("mid")),a["priority"]))
    denied=False
    for entry in ordered:
        account=dict(entry)
        name=account["name"]
        if denied:
            diagnostics.append({"account":name,"status":"not_attempted_after_denial"})
            continue
        stage="resolve_identity"
        try:
            if not account.get("mid"):
                account["mid"]=resolve(account)
            stage="account_uploads"
            result=fetch(account)
            if not isinstance(result,list):
                raise ValueError("Unexpected account archive shape")
            accepted=0
            for row in result:
                if not isinstance(row,dict):
                    continue
                normalized=normalize(row,account,now)
                if normalized and PROGRAMME_TITLE.search(normalized["title"]):
                    rows[normalized["bvid"]]=normalized
                    accepted+=1
            diagnostics.append({"account":name,"mid":str(account["mid"]),"status":"ok",
                                "stage":stage,"rows":len(result),"accepted":accepted})
        except Exception as exc:
            code=getattr(exc,"code",None)
            denied=isinstance(code,int) and code in DENIAL_CODES
            diagnostics.append({"account":name,"stage":stage,"status":"failed",
                                "error":type(exc).__name__,"httpStatus":code if isinstance(exc,urllib.error.HTTPError) else None,
                                "apiCode":code if isinstance(exc,MetadataResponseError) else None})
    candidates=sorted(rows.values(),key=lambda c:(-datetime.fromisoformat(c["publishedAt"]).timestamp(),c["priority"],c["bvid"]))
    groups={}
    for c in candidates:
        key=c["episodeKey"] or "unresolved:"+c["bvid"]
        groups.setdefault(key,[]).append(c)
    for members in groups.values():
        members.sort(key=lambda c:(c["priority"],-datetime.fromisoformat(c["publishedAt"]).timestamp(),c["bvid"]))
    return {"checkedAt":now.isoformat(),"status":"ok" if diagnostics and all(d["status"]=="ok" for d in diagnostics) else "degraded",
            "discoveryMode":"account_uploads","accounts":reg["accounts"],"diagnostics":diagnostics,"episodeGroups":groups,
            "candidateCount":len(candidates),"approvedSourceCount":len(reg["approvedSources"]),
            "autoAcquisitionAuthorized":bool(approval_records(reg)),"reason":"Only explicit approved-source records can be used for production; discovery itself grants no rights"}


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
