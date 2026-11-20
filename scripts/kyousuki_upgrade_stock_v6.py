"""Replace 23 v4 stock MP4/JSON pairs with visually reviewed v6 researched telop renders.

Safe/idempotent: verify the new pair, SHA256 and original episode before any move.
Move the complete old v4 pair to archive; move new JSON then MP4 into active stock.
Never touch manual YouTube uploads, reservation settings or previous v1 archives.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from packages.shared.gdrive import (get_drive_service, download_file_bytes,
                                     download_file_to_path, find_file, upload_json_data)
from scripts.kyousuki_stock_migration import children, verified_move

STOCK="1Y0XEnzTMpQbBvQVD8Uzfc6xbZYRU6ss8"
ARCHIVE="1wynQnpMGs76fRU9Ifkr-zaRs_IIOX7-Z"
REVIEW11="1dyWOKU48Xbw6fpyIhPdSEvoF7b2N-1wp"
REVIEW12="1PFm_HmuHQRn7oIXatftaYCKpAXXbOz9N"
LEDGER="kyousuki_v6_researched_telop_stock_migration.json"
MANUAL_VIDEO="posted_manual_7c6061c8e548ae5d0ffd1921.mp4"
EXPECTED={
    *(f"kyousuki_v2_ep2_clip_{i:03}.mp4" for i in range(1,7)),
    *(f"kyousuki_v2_ep3_clip_{i:03}.mp4" for i in range(1,7)),
    *(f"kyousuki_v2_ep4_clip_{i:03}.mp4" for i in range(1,6)),
    *(f"kyousuki_v2_ep5_clip_{i:03}.mp4" for i in range(1,7)),
}
SOURCES={
    2:"BV1FNnZ6mEM3",
    3:"BV1VX4P6qEwC",
    4:"BV1DzW86hE4H",
    5:"BV11GsK6RE2u",
}
RENDERER="source_episode_ffmpeg_v6_researched_telop"
EP_RE=re.compile(r"^kyousuki_v2_ep([2-5])_clip_\d{3}\.mp4$")
HEX=re.compile(r"^[a-f0-9]{64}$")


def sha256(path):
    with path.open("rb") as fh:
        return hashlib.file_digest(fh,"sha256").hexdigest()


def validated_receipts(manifest):
    if manifest.get("schemaVersion")!=6 or not isinstance(manifest.get("sourceRuns"),dict):
        raise ValueError("Invalid v6 visual review manifest")
    rows=manifest.get("items")
    if not isinstance(rows,list) or len(rows)!=len(EXPECTED):
        raise ValueError("All 23 visual review entries are mandatory")
    result={}
    for row in rows:
        name=row.get("name") if isinstance(row,dict) else None
        screenshots=row.get("screenshots") if isinstance(row,dict) else None
        if name not in EXPECTED or name in result or row.get("visualQa")!="pass":
            raise ValueError("Unapproved, invalid or duplicate clip")
        if not HEX.fullmatch(row.get("sha256") or ""):
            raise ValueError("Invalid video fingerprint")
        if set(screenshots or []) != {"beginning.png","middle.png","end.png"}:
            raise ValueError("Three distinct real inspection frames required")
        if not row.get("reviewedBy") or not str(row.get("artifactUrl") or "").startswith("https://github.com/"):
            raise ValueError("Missing review author or GitHub Actions artifact")
        result[name]=row
    return result


def meta_for(drive, file):
    return json.loads(download_file_bytes(drive,file["id"]))


def preflight(drive, manifest):
    approvals=validated_receipts(manifest)
    active={x["name"]:x for x in children(drive,STOCK)}
    oldarchive=children(drive,ARCHIVE)
    review={x["name"]:x for folder in (REVIEW11,REVIEW12) for x in children(drive,folder)}
    if MANUAL_VIDEO not in active:
        raise RuntimeError("Manual posted MP4 must remain untouched")
    results=[]
    for name in sorted(EXPECTED):
        match=EP_RE.fullmatch(name)
        episode=int(match.group(1))
        jsonname=name[:-4]+".json"
        new=review.get(name)
        newjson=review.get(jsonname)
        current=active.get(name)
        currentjson=active.get(jsonname)
        if current and currentjson:
            currentmeta=meta_for(drive,currentjson)
            existing=currentmeta.get("stockMigration") or {}
            if existing.get("designVersion")==6 and existing.get("qaStatus")=="pass":
                if existing.get("newMp4Sha256")!=approvals[name]["sha256"]:
                    raise RuntimeError("Already-active v6 does not match manifest: "+name)
                results.append({"name":name,"status":"already_active_v6",
                                "activeMp4Id":current["id"],"activeJsonId":currentjson["id"]})
                continue
        if not all([new,newjson,current,currentjson]):
            raise RuntimeError("Missing new/old paired video+JSON: "+name)
        fresh=meta_for(drive,newjson)
        old=meta_for(drive,currentjson)
        newmg=fresh.get("stockMigration") or {}
        oldmg=old.get("stockMigration") or {}
        a=fresh.get("kirinukiAudit") or {}
        olda=old.get("kirinukiAudit") or {}
        if (newmg.get("designVersion")!=6 or
            newmg.get("rebuildMethod")!=RENDERER or
            newmg.get("qaStatus") not in ("review_required","pass") or
            newmg.get("mediaIntegrityQa")!="pass" or
            int(newmg.get("subtitleBottomMargin") or 0)<650 or
            newmg.get("captionWrapped") is not True or
            newmg.get("template") != "telop" or
            not str(newmg.get("punchlineText") or "").strip() or
            not str(newmg.get("researchRef") or "").startswith("docs/design/README.md") or
            not str(newmg.get("hookText") or "").strip()):
            raise RuntimeError("Unreviewed or wrong editorial design: "+name)
        if (newmg.get("newMp4Sha256")!=approvals[name]["sha256"] or
            a.get("sourceContentId")!=SOURCES[episode] or
            olda.get("sourceContentId")!=SOURCES[episode] or
            newmg.get("sourceBvid")!=SOURCES[episode] or
            a.get("episodeKey")!=olda.get("episodeKey") or
            a.get("sourceUploaderMid")!=olda.get("sourceUploaderMid") or
            newmg.get("oldDriveMp4Id")!=oldmg.get("oldDriveMp4Id") or
            newmg.get("oldDriveJsonId")!=oldmg.get("oldDriveJsonId") or
            newmg.get("cutStartSeconds")!=oldmg.get("cutStartSeconds") or
            newmg.get("cutEndSeconds")!=oldmg.get("cutEndSeconds")):
            raise RuntimeError("Source episode/cut lineage mismatch: "+name)
        if fresh.get("topRichText") is None or fresh["topRichText"].strip()=="":
            raise RuntimeError("Hook commentary missing: "+name)
        if (int(new.get("size") or 0)!=int(newmg.get("newSizeBytes") or -1) or
            int(new.get("size") or 0)<100000 or
            fresh.get("videoFileName")!=name):
            raise RuntimeError("New MP4 metadata mismatch: "+name)
        results.append({"name":name,"status":"ready","new":new,"newJson":newjson,
                        "old":current,"oldJson":currentjson,"fresh":fresh,
                        "approval":approvals[name]})
    return results


def promote_one(drive,item):
    name=item["name"]
    new=item["new"]
    old=item["old"]
    with tempfile.TemporaryDirectory(prefix="kyousuki-v5-") as td:
        local=Path(td)/"new.mp4"
        download_file_to_path(drive,new["id"],local)
        if (sha256(local)!=item["approval"]["sha256"] or
                local.stat().st_size!=item["fresh"]["stockMigration"]["newSizeBytes"]):
            raise RuntimeError("Remote MP4 digest does not match reviewed media")
    meta=item["fresh"]
    mg=meta["stockMigration"]
    mg.update(qaStatus="pass",visualReviewedBy=item["approval"]["reviewedBy"],
              visualReviewEvidence=item["approval"]["artifactUrl"],
              replacedV4Mp4Id=old["id"],replacedV4JsonId=item["oldJson"]["id"])
    upload_json_data(drive,REVIEW11 if "_ep4_" in name or "_ep5_" in name else REVIEW12,
                     name[:-4]+".json",json.dumps(meta,ensure_ascii=False,indent=2).encode("utf-8"),
                     item["newJson"]["id"])
    source=REVIEW11 if "_ep4_" in name or "_ep5_" in name else REVIEW12
    operations=[]
    try:
        for file,src,dest in (
            (item["oldJson"],STOCK,ARCHIVE),
            (old,STOCK,ARCHIVE),
            (item["newJson"],source,STOCK),
            (new,source,STOCK),
        ):
            verified_move(drive,file["id"],src,dest)
            operations.append((file,src,dest))
    except Exception:
        for file,src,dest in reversed(operations):
            try:verified_move(drive,file["id"],dest,src)
            except Exception: pass
        raise
    return {"status":"replaced","name":name,"newMp4Id":new["id"],
            "newJsonId":item["newJson"]["id"],"archivedV4Mp4Id":old["id"],
            "archivedV4JsonId":item["oldJson"]["id"],
            "sha256":item["approval"]["sha256"]}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",type=Path,required=True)
    args=p.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    drive=get_drive_service()
    pending=preflight(drive,manifest)  # Validate all 23 before any move.
    report={"schemaVersion":6,"expected":23,"items":[],"complete":False}
    for item in pending:
        if item["status"]=="already_active_v6":
            report["items"].append(item)
            continue
        try:
            receipt=promote_one(drive,item)
            report["items"].append(receipt)
            print("KYOUSUKI_V6_REPLACED",json.dumps({"name":item["name"],"sha256":receipt["sha256"]}),flush=True)
        except Exception as exc:
            report["items"].append({"name":item["name"],"status":"failed","reason":str(exc)[:500]})
            break
    final={x["name"]:x for x in children(drive,STOCK)}
    archived=children(drive,ARCHIVE)
    archived_ids={x["id"] for x in archived}
    report["complete"]=(len(report["items"])==23 and
        all(x["status"] in ("replaced","already_active_v6") for x in report["items"]) and
        all(name in final and name[:-4]+".json" in final for name in EXPECTED) and
        all(x["id"] in archived_ids for row in report["items"] if row["status"]=="replaced"
            for x in [{"id":row["archivedV4Mp4Id"]},{"id":row["archivedV4JsonId"]}]) and
        MANUAL_VIDEO in final)
    prior=find_file(drive,STOCK,LEDGER)
    upload_json_data(drive,STOCK,LEDGER,json.dumps(report,ensure_ascii=False,indent=2).encode("utf-8"),
                     prior["id"] if prior else None)
    print("KYOUSUKI_V6_RECONCILIATION",json.dumps({"complete":report["complete"],
        "replaced":sum(x["status"]=="replaced" for x in report["items"]),
        "already":sum(x["status"]=="already_active_v6" for x in report["items"]),
        "archivedV4":len(archived),"activeClips":len(EXPECTED)}),flush=True)
    if not report["complete"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
