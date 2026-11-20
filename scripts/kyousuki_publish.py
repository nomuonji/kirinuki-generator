"""Publish only independently approved Kyousuki stock; never acquire blocked media.

The existing producer creates review stock, not final publication approvals.
No credential values, titles or Drive file IDs are printed by this command.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from packages.kyousuki_sources import approval_records, load_registry
from packages.publish_scheduler import aware, reserve_slots, utc_now

OFFICIAL_CHANNEL = "UCzXVsEc1h2Elljge0fnQYRg"
BVID = re.compile(r"BV[A-Za-z0-9]{10}")


def publication_item(metadata, folder, registry):
    """Validate exact provenance, independent media digest and editorial metadata."""
    if not isinstance(metadata,dict) or metadata.get("renderSpecVersion") != 2:
        return None
    migration = metadata.get("stockMigration")
    if not isinstance(migration, dict):
        return None
    # Editorial hooks + raised speech subtitles are mandatory before post.
    if (migration.get("qaStatus") != "pass" or migration.get("designVersion") != 7
            or migration.get("rebuildMethod") != "source_episode_ffmpeg_v7_researched_telop_soft_background"
            or not str(migration.get("hookText") or "").strip()
            or migration.get("captionWrapped") is not True
            or migration.get("template") != "telop"
            or migration.get("deadSpaceTreatment") != "dark_source_blur"
            or metadata.get("variant") not in (0,1,2)
            or migration.get("variant") != metadata.get("variant")
            or not str(migration.get("punchlineText") or "").strip()
            or not str(migration.get("researchRef") or "").startswith("docs/design/README.md")):
        return None
    audit = metadata.get("kirinukiAudit") if isinstance(metadata, dict) else None
    if not isinstance(audit, dict):
        return None
    if audit.get("sourcePlatform") != "bilibili":
        return None
    page = audit.get("sourcePage")
    if type(page) is not int or page < 1:
        return None
    bvid = audit.get("sourceContentId")
    mid = str(audit.get("sourceUploaderMid") or "")
    episode = audit.get("episodeKey")
    if (not isinstance(bvid,str) or not BVID.fullmatch(bvid)
            or not mid.isdigit() or not isinstance(episode,str)
            or not re.fullmatch(r"20[2-3]\d:[^:\r\n]{1,32}:[1-9]\d?", episode)
            or not any(str(a.get("mid")) == mid for a in registry.get("accounts",[]))):
        return None
    source_url = audit.get("sourceVideoUrl") or ""
    if not source_url.startswith(f"https://www.bilibili.com/video/{bvid}/"):
        return None
    digest = audit.get("publicationSha256")
    editorial = audit.get("approvedCandidateDigest")
    if not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return None
    if not isinstance(editorial,str) or not re.fullmatch(r"[a-f0-9]{64}",editorial):
        return None
    media = audit.get("media")
    if not isinstance(media,dict) or type(media.get("sizeBytes")) is not int or media["sizeBytes"] < 100000:
        return None
    title = audit.get("publicationTitle")
    description = audit.get("publicationDescription")
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 98:
        return None
    if not isinstance(description,str) or not 1 <= len(description.strip()) <= 3500:
        return None
    if re.search(r"KIRINUKI-(?:ID|SOURCE):",title+"\n"+description):
        return None
    # Same episode on another mirror has the same scheduling key.
    # Identical bytes cannot be re-uploaded even under another filename.
    source_id = "episode-" + hashlib.sha256(episode.encode()).hexdigest()[:24]
    key = hashlib.sha256(("kyousuki-stock-v1:"+digest).encode()).hexdigest()[:24]
    return {"fingerprint":key,"sourceId":source_id,"sourceUrl":source_url,
            "sha256":digest,"sizeBytes":media["sizeBytes"],"title":title.strip(),
            "description":description.strip()}


def verified_stock_folder(drive, folder):
    meta = drive.files().get(fileId=folder,fields="name,parents,mimeType,trashed").execute()
    if meta.get("name") != "short" or meta.get("mimeType") != "application/vnd.google-apps.folder" or meta.get("trashed"):
        return False
    parents = meta.get("parents") or []
    if len(parents)!=1:
        return False
    parent = drive.files().get(fileId=parents[0],fields="name,trashed").execute()
    return parent.get("name")=="kyo-suki" and not parent.get("trashed")


def eligible_items(drive, folder, registry):
    from packages.shared.gdrive import list_clip_files, download_file_bytes
    files=list_clip_files(drive,folder)
    ready=[]
    for f in files:
        # Use a unique sibling sidecar, not whatever first match Drive returns.
        name=f["name"][:-4]+".json"
        escaped=name.replace("\\","\\\\").replace("'","\\'")
        matches=drive.files().list(q=f"'{folder}' in parents and name = '{escaped}' and trashed=false",
            fields="nextPageToken,files(id,size,mimeType)",pageSize=2).execute()
        rows=matches.get("files",[])
        if len(rows)!=1 or matches.get("nextPageToken"):
            continue
        sidecar=rows[0]
        if sidecar.get("mimeType")!="application/json" or int(sidecar.get("size") or 0)>2_000_000:
            continue
        try:
            metadata=json.loads(download_file_bytes(drive,sidecar["id"]))
        except (ValueError,UnicodeError):
            continue
        item=publication_item(metadata,folder,registry)
        if item and int(f.get("size") or 0)==item["sizeBytes"]:
            ready.append((f,item))
    return len(files),ready


def readiness():
    env=os.environ
    registry=load_registry()
    folder=env.get("GDRIVE_PARENT_FOLDER_ID","")
    destination=env.get("YOUTUBE_DESTINATION_CHANNEL_ID","")
    # No arbitrary yes/no activation flags. Verify OAuth identity and content.
    oauth_keys=("YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET",
                "YOUTUBE_REFRESH_TOKEN","YOUTUBE_DESTINATION_CHANNEL_ID")
    missing_keys=[key for key in oauth_keys if not str(env.get(key) or "").strip()]
    enabled,why=(False, "missing: "+", ".join(missing_keys)) if missing_keys else (True,"oauth_configured")
    report={"enabledByConfiguration":enabled,"activation":why,
        "approvedSources":sum(r["stockFolderId"]==folder for r in approval_records(registry)),
        "destinationConfigured":bool(destination),
        "oauthConfigured":all(bool(env.get(k)) for k in ("YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN")),
        "destinationCheck":"not_configured","stockFolderCheck":"not_configured","stockClips":None,
        "publicationApprovedClips":None,"blockers":[]}
    blockers=report["blockers"]
    drive=None
    ready=[]
    if folder and all(env.get(k) for k in ("GDRIVE_CLIENT_SECRET_JSON","GDRIVE_REFRESH_TOKEN")):
        try:
            from packages.shared.gdrive import get_drive_service
            candidate=get_drive_service()
            if verified_stock_folder(candidate,folder):
                report["stockFolderCheck"]="verified"
                report["stockClips"],ready=eligible_items(candidate,folder,registry)
                report["publicationApprovedClips"]=len(ready)
                drive=candidate
            else:
                report["stockFolderCheck"]="wrong_folder"
        except Exception as exc:
            report["stockFolderCheck"]="failed_"+type(exc).__name__
    yt=playlist=None
    if destination and destination!=OFFICIAL_CHANNEL and report["oauthConfigured"]:
        try:
            from packages.youtube_direct import auth_youtube
            yt,playlist=auth_youtube()
            report["destinationCheck"]="verified"
        except Exception as exc:
            report["destinationCheck"]="failed_"+type(exc).__name__
    elif destination==OFFICIAL_CHANNEL:
        report["destinationCheck"]="source_channel_is_not_destination"
    if not enabled: blockers.append("activation_or_oauth_missing")
    if report["stockFolderCheck"]!="verified": blockers.append("stock_folder_unverified")
    elif not report["stockClips"]: blockers.append("stock_empty")
    elif not ready: blockers.append("publication_receipts_missing")
    if report["destinationCheck"]!="verified": blockers.append("destination_unverified")
    report["readyToSchedule"]=not blockers
    return report,drive,ready,yt,playlist


def confirmed_remote(remote,item,slot):
    from packages.youtube_direct import fingerprint_of
    status=(remote or {}).get("status") or {}
    try:
        return (fingerprint_of(remote or {})==item["fingerprint"]
                and status.get("privacyStatus")=="private"
                and bool(status.get("publishAt"))
                and aware(status["publishAt"])==aware(slot))
    except (ValueError,TypeError):
        return False


def execute(drive,items,yt,playlist):
    """At most one new private reservation. Ambiguous attempts never auto-retry."""
    from packages.github_ledger import GitHubLedger
    from packages.shared.gdrive import download_file_to_path
    from packages.quality_gate import verify_rendered_media
    from packages.youtube_direct import (owned_videos, reservations, fingerprint_of,
                                         upload_once, readback_video, UploadDeferred)
    ledger=GitHubLedger("kyousuki-approved-stock")
    ledger.load()
    actual=owned_videos(yt,playlist,limit=250)
    remote_keys={fingerprint_of(v):v for v in actual if fingerprint_of(v)}
    slots=reservations(actual)
    for record in ledger.data["clips"].values():
        if record.get("publishAt") and record.get("status")!="rejected":
            slots.append({"publishAt":record["publishAt"],"sourceVideoId":record.get("sourceId")})
    for f,item in items:
        key=item["fingerprint"]
        prior=ledger.clip(key)
        if prior or key in remote_keys:
            # Never blindly retry an unresolved upload. Retain stock for reconciliation.
            continue
        choices=reserve_slots(slots,days=7,max_count=1,source_id=item["sourceId"])
        if not choices:
            return "no_slot"
        slot=choices[0]
        with tempfile.TemporaryDirectory(prefix="kyousuki-stock-") as tmp:
            path=Path(tmp)/"approved.mp4"
            download_file_to_path(drive,f["id"],path)
            with path.open("rb") as fh:
                digest=hashlib.file_digest(fh,"sha256").hexdigest()
            if digest!=item["sha256"] or path.stat().st_size!=item["sizeBytes"]:
                raise RuntimeError("Approved stock integrity mismatch")
            verify_rendered_media(path)
            ledger.set_clip(key,status="uploading",sourceId=item["sourceId"],
                            attemptedAt=utc_now().isoformat(),publishAt=slot)
            try:
                receipt=upload_once(yt,path,title=item["title"],description=item["description"],
                    source_video_id=item["sourceId"],source_url=item["sourceUrl"],
                    fingerprint=key,publish_at=slot)
            except UploadDeferred:
                # Explicit rejection is recorded and left for operator review.
                ledger.set_clip(key,status="rejected")
                raise
            ledger.set_clip(key,status="verification_pending",videoId=receipt["videoId"],
                            uploadedAt=receipt["uploadedAt"])
            remote=readback_video(yt,receipt["videoId"])
            if not confirmed_remote(remote,item,slot):
                raise RuntimeError("YouTube reservation is not verified")
            ledger.set_clip(key,status="scheduled",videoId=receipt["videoId"],publishAt=slot)
            # Preserve the exact original MP4; remove it from the producer's
            # _clip_ stock count only after durable reservation readback.
            drive.files().update(fileId=f["id"],body={"name":"scheduled_"+key+".mp4"},fields="id").execute()
            return "scheduled"
    return "no_new_approved_clip"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--execute",action="store_true")
    p.add_argument("--require-ready",action="store_true",help="Fail a production readiness check if scheduling is blocked")
    args=p.parse_args()
    report,drive,items,yt,playlist=readiness()
    print("KYOUSUKI_PUBLISH_READINESS",json.dumps(report,ensure_ascii=False),flush=True)
    if not args.execute:
        if args.require_ready and not report["readyToSchedule"]:
            raise SystemExit("Publication blocked: "+", ".join(report["blockers"]))
        return
    if not report["readyToSchedule"]:
        raise SystemExit("Publication blocked: "+", ".join(report["blockers"]))
    try:
        print("KYOUSUKI_PUBLISH_RESULT",execute(drive,items,yt,playlist))
    except Exception as exc:
        raise SystemExit("Publication stopped: "+type(exc).__name__) from None


if __name__=="__main__":
    main()
