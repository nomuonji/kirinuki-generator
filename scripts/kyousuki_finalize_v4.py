"""One-time, idempotent migration of explicitly visually reviewed v4 source cuts.

This does not change YouTube activation, publish permissions, reservation times,
or the already-posted video. It is intentionally separate from normal stock logic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from packages.shared.gdrive import get_drive_service, download_file_bytes, find_file, upload_json_data
from scripts.kyousuki_stock_migration import children, plan, migrate

EXPECTED = {
    *(f"kyousuki_v2_ep4_clip_{i:03}.mp4" for i in range(1,6)),
    *(f"kyousuki_v2_ep5_clip_{i:03}.mp4" for i in range(1,7)),
}
MANUAL_POSTED_NAME = "posted_manual_7c6061c8e548ae5d0ffd1921.mp4"
LEDGER_NAME = "kyousuki_v4_final_migration.json"

def parse_review(data):
    """Review receipts contain three real screenshots per independently reviewed clip."""
    if not isinstance(data,dict) or data.get("schemaVersion")!=1:
        raise ValueError("Invalid visual review manifest version")
    if not isinstance(data.get("sourceRunId"),int) or data["sourceRunId"]<=0:
        raise ValueError("Source GitHub Actions run ID is mandatory")
    rows=data.get("items")
    if not isinstance(rows,list) or len(rows)!=len(EXPECTED):
        raise ValueError("Exactly eleven reviewed clips required")
    result={}
    for row in rows:
        if not isinstance(row,dict): raise ValueError("Invalid reviewed row")
        name=row.get("name")
        sha=row.get("sha256")
        samples=row.get("screenshots")
        if name not in EXPECTED or name in result or row.get("visualQa")!="pass":
            raise ValueError("Missing, duplicate or unapproved clip")
        if not isinstance(sha,str) or not re.fullmatch("[a-f0-9]{64}",sha):
            raise ValueError("Invalid source-media SHA256")
        if not isinstance(samples,list) or set(samples)!={"beginning.png","middle.png","end.png"}:
            # renderer uses beginning/middle/end names, some legacy uses opening.
            raise ValueError("All actual opening, middle and end frames required")
        if not row.get("reviewedBy") or not row.get("evidenceArtifactUrl"):
            raise ValueError("Visual QA reviewer and real evidence location required")
        result[name]=row
    if set(result)!=EXPECTED: raise ValueError("Missing reviewed clip")
    return result

def promote(drive,stock,review,quarantine,manifest):
    approvals=parse_review(manifest)
    if len(children(drive,quarantine)) != 22:
        raise RuntimeError("Legacy archived video/JSON inventory changed unexpectedly")
    before={row["name"]:row for row in children(drive,stock)}
    posted=before.get(MANUAL_POSTED_NAME)
    if not posted:
        raise RuntimeError("Manual published video no longer present; stop")
    staging={row["name"]:row for row in plan(drive,stock,review,quarantine)}
    already={}
    for name in EXPECTED:
        if name in before:
            side=before.get(name[:-4]+".json")
            if not side: raise RuntimeError("Orphan v4 video in active stock")
            data=json.loads(download_file_bytes(drive,side["id"]))
            qa=data.get("stockMigration") or {}
            if qa.get("qaStatus")!="pass" or qa.get("newMp4Sha256")!=approvals[name]["sha256"]:
                raise RuntimeError("Active v4 clip is not matching approved manifest")
            already[name]={"status":"already_active","mp4Id":before[name]["id"],
                           "jsonId":side["id"],"sha256":approvals[name]["sha256"]}
    outstanding=EXPECTED-set(already)
    if not outstanding.issubset(set(staging)):
        raise RuntimeError("Missing v4 pairs in staging/active Drive")
    for name in sorted(outstanding):
        item=staging[name]
        errors=set(item["errors"])
        if errors-{"visual_qa_not_passed"}:
            raise RuntimeError("Source QA/provenance mismatch for "+name+": "+",".join(errors))
        metadata=item.get("metadata") or {}
        migration=metadata.get("stockMigration") or {}
        if (migration.get("rebuildMethod")!="source_episode_ffmpeg_v4_catbadge_face_safe"
                or migration.get("newMp4Sha256")!=approvals[name]["sha256"]):
            raise RuntimeError("Unexpected renderer or hash "+name)
        migration["qaStatus"]="pass"
        migration["visualReviewedBy"]=approvals[name]["reviewedBy"]
        migration["visualEvidenceArtifact"]=approvals[name]["evidenceArtifactUrl"]
        migration["visualNotes"]=approvals[name].get("notes","")
        metadata["stockMigration"]=migration
        upload_json_data(drive,review,name[:-4]+".json",
            json.dumps(metadata,ensure_ascii=False,indent=2).encode("utf-8"),
            item["sourceJsonId"])
    approved={row["name"]:row for row in plan(drive,stock,review,quarantine)}
    if not outstanding.issubset(set(approved)):
        raise RuntimeError("Reconciliation after sidecar update failed")
    for name in outstanding:
        if approved[name]["status"]!="eligible":
            raise RuntimeError("Not eligible despite visual approval: "+name)
    receipts=dict(already)
    for name in sorted(outstanding):
        try:
            receipt=migrate(drive,approved[name],stock,review)
            receipts[name]={"status":"promoted",**receipt}
            print("KYOUSUKI_V4_PROMOTE",json.dumps({"name":name,**receipt}),flush=True)
        except Exception as exc:
            receipts[name]={"status":"failed","error":type(exc).__name__}
            # Preserve old quarantined clips and remaining review stock on failure.
            break
    current={row["name"]:row for row in children(drive,stock)}
    complete=len(receipts)==len(EXPECTED) and all(x["status"] in ("promoted","already_active") for x in receipts.values())
    for name in EXPECTED:
        if name not in current or name[:-4]+".json" not in current:
            complete=False
    if MANUAL_POSTED_NAME not in current or current[MANUAL_POSTED_NAME]["id"]!=posted["id"]:
        complete=False
    report={"schemaVersion":4,"sourceRunId":manifest["sourceRunId"],
            "expected":11,"promotedOrPreviouslyActive":sum(x["status"] in ("promoted","already_active") for x in receipts.values()),
            "complete":complete,"results":receipts,
            "manualPostedUntouched":MANUAL_POSTED_NAME in current and current[MANUAL_POSTED_NAME]["id"]==posted["id"],
            "archivedLegacyPairs":11}
    prior=find_file(drive,stock,LEDGER_NAME)
    upload_json_data(drive,stock,LEDGER_NAME,json.dumps(report,ensure_ascii=False,indent=2).encode("utf-8"),
                     prior["id"] if prior else None)
    if not complete:
        raise RuntimeError("Final Drive stock reconciliation incomplete")
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--stock-folder",default="1Y0XEnzTMpQbBvQVD8Uzfc6xbZYRU6ss8")
    p.add_argument("--quarantine-folder",default="1WXqO4BN_6TlFpCdcJduFHd6lNtKSIFXU")
    p.add_argument("--review-folder",default="11W4KuH3Tdzi7vzVE857vNKqcxG0vrehO")
    args=p.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    result=promote(get_drive_service(),args.stock_folder,args.review_folder,args.quarantine_folder,manifest)
    print("KYOUSUKI_V4_FINAL",json.dumps({"complete":result["complete"],
        "promotedOrPreviouslyActive":result["promotedOrPreviouslyActive"]},ensure_ascii=False))

if __name__=="__main__":
    main()
