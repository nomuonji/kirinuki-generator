"""Scheduled Kyousuki metadata discovery; account hints are not licensing evidence."""
from __future__ import annotations
import argparse
import html
import json
import os
import re
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


def catalog_stock_candidates(discovery, processed_entries, reg=None, now=None, max_age_days=90):
    """Select account-bound catalog rows, independently of per-video registration.

    This is an operational source selection rule, not a license determination.
    The user remains responsible for lawful use. Never manufacture rights receipts.
    """
    if discovery.get("status") != "ok" or discovery.get("discoveryMode") != "public_catalog":
        return []
    reg = reg or load_registry()
    now = now or datetime.now(timezone.utc)
    byid = {p.get("videoId"): p for p in processed_entries}
    rows = {}
    for group in discovery.get("episodeGroups", {}).values():
        for row in group:
            if row.get("metadataProvider") != "uapipro" or row.get("identityStatus") != "catalog_account_binding":
                continue
            account = next((a for a in reg["accounts"] if a.get("mid") and str(a["mid"]) == row.get("mid") and a["name"] == row.get("author")), None)
            if not account:
                continue
            try:
                posted = datetime.fromisoformat(row["publishedAt"].replace("Z","+00:00"))
                age = (now-posted).total_seconds()/86400
                title = row["title"]
                duration = row["durationSeconds"]
                if not 0 <= age <= max_age_days or not FULL_EP.search(title) or EXTRAS.search(title):
                    continue
                if not re.search(r"今天喜欢上你了|今天喜欢你了|今喜|今日好き", title):
                    continue
                item = normalize({"bvid":row["bvid"],"author":account["name"],"mid":str(account["mid"]),
                    "title":title,"duration":duration,"pubdate":int(posted.timestamp())},account,now)
            except (KeyError,ValueError,TypeError,OverflowError):
                continue
            if not item:
                continue
            sid = f'bilibili_{item["bvid"]}_p1_auto'
            ep = item["episodeKey"]
            # Unknown season aliases still dedupe by exact BV; don't invent official EP identity.
            related = [e for e in processed_entries if e.get("videoId")==sid or (ep and e.get("episodeKey")==ep)]
            if any(e.get("status")=="completed" or (e.get("videoId")!=sid and int(e.get("uploadedClips") or 0)>0) for e in related):
                continue
            prior = byid.get(sid,{})
            if int(prior.get("attempts") or 0)>=3:
                continue
            if prior.get("processedAt"):
                try:
                    if (now-datetime.fromisoformat(prior["processedAt"].replace("Z","+00:00"))).total_seconds()<21600:
                        continue
                except (ValueError,TypeError):
                    continue
            rows[sid] = {"videoId":sid,"sourcePlatform":"bilibili","bvid":item["bvid"],"page":1,
                "mid":item["mid"],"author":item["author"],"episodeKey":ep,"title":title,
                "publishedAt":item["publishedAt"],"ageHours":age*24,"durationSeconds":duration,
                "selectionScore":0.82 if age<=1 else 0.65,"viewsPerHour":0.0,"views":0,"likes":0,"comments":0,
                "priority":account["priority"],"selectionMode":"catalog"}
    return sorted(rows.values(),key=lambda r:(-datetime.fromisoformat(r["publishedAt"]).timestamp(),r["priority"],r["videoId"]))

def catalog_source_identity(bvid, mid, reg=None):
    """Bind the selected BV to a configured numeric uploader; media adapter checks actual MID."""
    reg = reg or load_registry()
    if not isinstance(bvid,str) or not BVID.fullmatch(bvid) or not isinstance(mid,str) or not mid.isdigit():
        raise ValueError("Invalid catalog source identity")
    if not any(str(a.get("mid"))==mid for a in reg["accounts"] if a.get("mid")):
        raise ValueError("Uploader outside the configured catalog accounts")
    return mid


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



def indexed_discovery(path, reg, now):
    """Consume an external public search index snapshot as hints only.

    The data branch is not an executable source or an approval authority. Do
    not infer uploader MID, publication timestamp, duration, or license from
    SERP snippets. A stale or malformed snapshot never triggers direct search.
    """
    report = {"checkedAt": now.isoformat(), "status": "degraded",
              "discoveryMode": "public_index", "accounts": reg["accounts"],
              "diagnostics": [], "episodeGroups": {}, "candidateCount": 0,
              "indexHints": [], "indexHintCount": 0,
              "approvedSourceCount": len(reg["approvedSources"]),
              "autoAcquisitionAuthorized": bool(approval_records(reg)),
              "reason": "Index hits are metadata only; exact documented source grants alone authorize production."}
    def failure(code):
        report["diagnostics"] = [{"stage": "index_snapshot", "status": "failed", "reason": code}]
        return report
    def fresh(value):
        if not isinstance(value, str):
            return False
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.tzinfo is not None and -300 <= (now-dt).total_seconds() <= 72*3600
        except (ValueError, TypeError, OverflowError):
            return False
    try:
        with Path(path).open("rb") as fh:
            data = json.loads(fh.read(256_001))
    except (OSError, UnicodeError, ValueError):
        return failure("missing_or_invalid_index")
    if (not isinstance(data, dict) or data.get("schemaVersion") != 1
            or data.get("purpose") != "public_metadata_only"
            or data.get("provider") != "brightdata"):
        return failure("invalid_index_contract")
    if not fresh(data.get("writtenAt")):
        return failure("stale_index")
    rows = data.get("rows")
    if not isinstance(rows, list) or len(rows) > 40:
        return failure("invalid_index_rows")
    names = {a["name"] for a in reg["accounts"]}
    hits = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid = row.get("bvid")
        title = row.get("title")
        account = row.get("accountHint")
        query = row.get("query")
        if (not isinstance(bid, str) or not BVID.fullmatch(bid)
                or row.get("url") not in (f"https://www.bilibili.com/video/{bid}/", f"https://www.bilibili.com/video/{bid}")
                or not isinstance(account, str) or account not in names
                or not isinstance(title, str) or not 1 <= len(title) <= 240
                or not re.search(r"今天喜欢上你了|今天喜欢你了|今喜|今日好き", title)
                or EXTRAS.search(title)
                or not isinstance(query, str) or len(query) > 500 or account not in query
                or not fresh(row.get("fetchedAt"))):
            continue
        # No opaque row passthrough. In particular no rights, MID or date fields.
        hits[bid] = {"bvid": bid, "url": f"https://www.bilibili.com/video/{bid}/",
                     "title": _clean(title), "accountHint": account,
                     "episodeKeyHint": episode_key(title),
                     "fetchedAt": row["fetchedAt"], "query": query,
                     "approvalStatus": "metadata_only"}
    report["indexHints"] = list(hits.values())
    report["indexHintCount"] = len(hits)
    report["status"] = "ok" if hits else "degraded"
    report["diagnostics"] = [{"stage": "index_snapshot", "status": report["status"],
                              "acceptedHints": len(hits), "inputRows": len(rows)}]
    return report



def public_catalog(mid, timeout=15):
    """Documented third-party public metadata catalog; guest access only.

    No Bilibili credentials, proxy parameters, retries or quota evasion.
    A capped guest allowance is not an unlimited or paid subscription.
    """
    url = "https://uapis.cn/api/v1/social/bilibili/archives?" + urllib.parse.urlencode(
        {"mid": mid, "ps": 20, "pn": 1, "orderby": "pubdate"})
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("catalog payload exceeds limit")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("videos"), list):
            raise ValueError("catalog result unavailable")
        if len(data["videos"]) > 20:
            raise ValueError("catalog result exceeds requested limit")
        remaining = response.headers.get("X-RateLimit-Remaining")
        return data["videos"], int(remaining) if remaining and remaining.isdecimal() else None


def catalog_discovery(reg, now, index_path=None, fetch=public_catalog):
    """Inspect each configured account independently; group only exact recognized episode keys.

    Old uploads never suppress newer episodes from another account. Every provider
    consumes at most one bounded public archive request; access failure is reported.
    Metadata discovery does not authorize downloading or redistribution.
    """
    report = indexed_discovery(index_path, reg, now) if index_path else {
        "checkedAt": now.isoformat(), "accounts": reg["accounts"],
        "indexHints": [], "indexHintCount": 0, "diagnostics": [],
        "approvedSourceCount": len(reg["approvedSources"]),
        "autoAcquisitionAuthorized": bool(approval_records(reg))}
    report.update({"discoveryMode": "public_catalog", "status": "degraded",
                   "episodeGroups": {}, "candidateCount": 0,
                   "reason": "Catalog metadata is not authorization; source grants and frame QA are required."})
    found = {}
    successful = 0
    for account in sorted(reg["accounts"], key=lambda a: a["priority"]):
        mid = str(account.get("mid") or "")
        diag = {"stage": "public_catalog", "provider": "uapipro",
                "account": account["name"], "mid": mid}
        report["diagnostics"].append(diag)
        if not mid.isdigit():
            diag.update(status="failed", reason="unverified_mid")
            continue
        try:
            raw, remaining = fetch(mid)
        except Exception as exc:
            diag.update(status="failed", error=type(exc).__name__,
                        httpStatus=getattr(exc, "code", None))
            if getattr(exc, "code", None) in (401, 403, 412, 429):
                break
            continue
        successful += 1
        accepted = 0
        for r in raw:
            if not isinstance(r, dict):
                continue
            title = _clean(r.get("title"))
            if not re.search(r"今天喜欢上你了|今天喜欢你了|今喜|今日好き", title):
                continue
            if not FULL_EP.search(title) or EXTRAS.search(title):
                continue
            paid = r.get("is_ugc_pay", r.get("isugcpay"))
            if r.get("state") != 0 or paid not in (0, False):
                continue
            stamp = r.get("publish_time", r.get("publishtime"))
            duration = r.get("duration")
            if type(duration) is not int or type(stamp) is bool:
                continue
            candidate = normalize({"bvid": r.get("bvid"), "title": title,
                                   "author": account["name"], "mid": mid,
                                   "duration": duration, "pubdate": stamp}, account, now)
            if candidate:
                candidate["metadataProvider"] = "uapipro"
                candidate["identityStatus"] = "catalog_account_binding"
                found[candidate["bvid"]] = candidate
                accepted += 1
        diag.update(status="ok", returnedRows=len(raw),
                    acceptedRows=accepted, rateLimitRemaining=remaining)
    for candidate in found.values():
        key = candidate["episodeKey"] or "unresolved:" + candidate["bvid"]
        report["episodeGroups"].setdefault(key, []).append(candidate)
    for group in report["episodeGroups"].values():
        group.sort(key=lambda c: (c["priority"], -datetime.fromisoformat(c["publishedAt"]).timestamp(), c["bvid"]))
    report["candidateCount"] = len(found)
    report["status"] = "ok" if successful and found else "degraded"
    report["latestCatalogCandidate"] = max(found.values(), key=lambda c:c["publishedAt"]) if found else None
    return report



def discover(reg=None, fetch=search, now=None):
    reg=reg or load_registry()
    now=now or datetime.now(timezone.utc)
    index_path = os.environ.get("KYOUSUKI_INDEX_FILE")
    if os.environ.get("KYOUSUKI_PUBLIC_CATALOG") == "1":
        return catalog_discovery(reg, now, index_path)
    if index_path:
        return indexed_discovery(index_path, reg, now)
    names={a["name"]:a for a in reg["accounts"]}
    rows={}
    diagnostics=[]
    # Use the user's marked uploaders as query inputs, not merely result filters.
    # Start with account-targeted ordinary public search, then broad discovery.
    # An access denial stops the entire lookup; do not rotate endpoints or retry.
    keywords = list(dict.fromkeys(
        [a["name"] + " " + reg["searchKeywords"][0]
         for a in sorted(reg["accounts"], key=lambda a: a["priority"])
         if reg["searchKeywords"]]
        + reg["searchKeywords"]
    ))
    for kw in keywords:
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
            "autoAcquisitionAuthorized":bool(approval_records(reg)),"reason":"Only explicit approved-source records can be used for production; discovery itself grants no rights"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    data=discover()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("KYOUSUKI_DISCOVERY",json.dumps({"status":data["status"],"candidates":data["candidateCount"],
         "approved":data["approvedSourceCount"],"indexHints":data.get("indexHintCount",0),"diagnostics":data["diagnostics"]},ensure_ascii=False))


if __name__=="__main__":
    main()
