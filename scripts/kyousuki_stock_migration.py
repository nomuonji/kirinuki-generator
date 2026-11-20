"""Crash-safe migration of quality-approved review stock into the Kyousuki posting folder.

This lane never generates episodes or publishes to YouTube. Old stock remains in its
quarantine folder. The existing processed_videos ledger is not consulted to decide
whether a quality-only upgrade is due. The input must be a complete v2 MP4/JSON pair
with matching source lineage, verified bytes, and final visual QA status.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from packages.shared.gdrive import (get_drive_service, download_file_bytes,
                                     download_file_to_path, find_file, upload_json_data)

BVID = re.compile(r"BV[A-Za-z0-9]{10}")
STEM = re.compile(r"kyousuki_v2_ep[1-9][0-9]?_clip_[0-9]{3}")
REPORT_NAME = "kyousuki_stock_v2_migration_ledger.json"


def children(drive, folder):
    rows = []
    token = None
    while True:
        response = drive.files().list(q=f"'{folder}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,size,mimeType,md5Checksum,parents)",
            pageSize=100, pageToken=token).execute()
        rows.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            break
    return rows


def inspect_pair(mp4, sidecar, metadata, quarantine_names):
    """Reject before any write unless lineage and final quality verdict are exact."""
    errors = []
    audit = metadata.get("kirinukiAudit") or {}
    upgrade = metadata.get("stockMigration") or {}
    name = str(mp4.get("name", ""))
    stem = name[:-4] if name.endswith(".mp4") else ""
    if not STEM.fullmatch(stem):
        errors.append("invalid_v2_filename")
    if sidecar.get("name") != stem + ".json":
        errors.append("mismatched_json")
    if metadata.get("renderSpecVersion") != 2 or upgrade.get("renderSpecVersion") != 2:
        errors.append("old_render_spec")
    if upgrade.get("qaStatus") != "pass":
        errors.append("visual_qa_not_passed")
    if upgrade.get("mediaIntegrityQa") != "pass":
        errors.append("media_integrity_qa_not_passed")
    if upgrade.get("manualPostedExcluded") is True:
        errors.append("manual_posted")
    bvid = audit.get("sourceContentId")
    if not isinstance(bvid,str) or not BVID.fullmatch(bvid) or bvid != upgrade.get("sourceBvid"):
        errors.append("source_bvid_mismatch")
    if not audit.get("episodeKey") or audit.get("episodeKey") != upgrade.get("episodeKey"):
        errors.append("source_episode_mismatch")
    if str(audit.get("sourceUploaderMid")) != str(upgrade.get("sourceUploaderMid")):
        errors.append("source_uploader_mismatch")
    if (not upgrade.get("oldDriveMp4Id") or not upgrade.get("oldDriveJsonId")
            or upgrade["oldDriveMp4Id"] not in quarantine_names
            or upgrade["oldDriveJsonId"] not in quarantine_names):
        errors.append("legacy_pair_not_in_quarantine")
    sha = upgrade.get("newMp4Sha256")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha):
        errors.append("invalid_sha256")
    try:
        size = int(mp4.get("size",0))
        if size < 100000 or int(upgrade.get("newSizeBytes",0)) != size:
            errors.append("size_mismatch")
    except (TypeError,ValueError):
        errors.append("invalid_size")
    if metadata.get("videoFileName") != name:
        errors.append("video_filename_mismatch")
    return errors


def plan(drive, stock_folder, review_folder, quarantine_folder):
    staging = children(drive, review_folder)
    archived = {x["id"] for x in children(drive,quarantine_folder)}
    active = {x["name"]:x for x in children(drive,stock_folder)}
    by_name = {x["name"]:x for x in staging}
    results=[]
    for item in staging:
        name = item.get("name", "")
        if not name.endswith(".mp4") or not name.startswith("kyousuki_v2_"):
            continue
        js = by_name.get(name[:-4]+".json")
        errors=[]
        metadata=None
        if not js:
            errors.append("missing_sidecar")
        else:
            try:
                metadata=json.loads(download_file_bytes(drive,js["id"]))
                errors.extend(inspect_pair(item,js,metadata,archived))
            except (ValueError,UnicodeError):
                errors.append("invalid_sidecar_json")
        if item["name"] in active or (js and js["name"] in active):
            errors.append("already_in_posting_stock")
        results.append({"name":name,"sourceMp4Id":item["id"],
            "sourceJsonId":js["id"] if js else None,
            "status":"eligible" if not errors else "held",
            "errors":errors,"metadata":metadata})
    return results


def verified_move(drive, file_id, src, dest):
    out=drive.files().update(fileId=file_id,addParents=dest,removeParents=src,
        fields="id,name,parents,size,md5Checksum").execute()
    if dest not in (out.get("parents") or []):
        raise RuntimeError("Drive move readback failed")
    return out


def migrate(drive, item, stock, review):
    metadata=item["metadata"]
    expected=metadata["stockMigration"]["newMp4Sha256"]
    with tempfile.TemporaryDirectory(prefix="kyo-migrate-") as td:
        video=Path(td)/"clip.mp4"
        download_file_to_path(drive,item["sourceMp4Id"],video)
        with video.open("rb") as f:
            digest=hashlib.file_digest(f,"sha256").hexdigest()
        if digest != expected or video.stat().st_size != metadata["stockMigration"]["newSizeBytes"]:
            raise RuntimeError("new_remote_file_integrity_failure")
    # Move sidecar first, then MP4, so the stock planner cannot see a partial clip.
    side_id=item["sourceJsonId"]
    video_id=item["sourceMp4Id"]
    verified_move(drive,side_id,review,stock)
    try:
        verified_move(drive,video_id,review,stock)
    except Exception:
        verified_move(drive,side_id,stock,review)
        raise
    return {"newMp4Id":video_id,"newJsonId":side_id,"sha256":expected,
            "version":2,"sourceBvid":metadata["stockMigration"]["sourceBvid"],
            "oldDriveMp4Id":metadata["stockMigration"]["oldDriveMp4Id"]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review-folder",required=True)
    p.add_argument("--quarantine-folder",required=True)
    p.add_argument("--stock-folder",default=os.environ.get("GDRIVE_PARENT_FOLDER_ID",""))
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    if not all((args.review_folder,args.quarantine_folder,args.stock_folder)):
        p.error("all folder IDs required")
    drive=get_drive_service()
    items=plan(drive,args.stock_folder,args.review_folder,args.quarantine_folder)
    ledger={"version":2,"reviewFolder":args.review_folder,"quarantineFolder":args.quarantine_folder,
            "postingFolder":args.stock_folder,"items":[]}
    for item in items:
        row={"name":item["name"],"status":item["status"],"errors":item["errors"]}
        if args.execute and item["status"]=="eligible":
            try:
                row.update(status="promoted",**migrate(drive,item,args.stock_folder,args.review_folder))
            except Exception as exc:
                row.update(status="failed",errors=[type(exc).__name__])
        ledger["items"].append(row)
    if args.execute:
        prior=find_file(drive,args.stock_folder,REPORT_NAME)
        upload_json_data(drive,args.stock_folder,REPORT_NAME,ledger,prior["id"] if prior else None)
    summary={"reviewed":len(items),"promoted":sum(i["status"]=="promoted" for i in ledger["items"]),
             "held":sum(i["status"]=="held" for i in ledger["items"]),
             "failed":sum(i["status"]=="failed" for i in ledger["items"])}
    print("KYOUSUKI_STOCK_MIGRATION",json.dumps(summary,ensure_ascii=False))
    if summary["failed"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
