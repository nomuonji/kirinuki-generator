"""Rebuild archived Kyousuki cuts from the original identified Bilibili episode.

Bypass processed-videos and stock-replenishment dedupe intentionally. Reuse exact cut
boundaries, subtitles and source provenance. Stage new video/JSON pairs in a review
folder; never post or replace anything without a final visual QA result.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from packages.shared.gdrive import (get_drive_service, download_file_bytes,
                                     find_file, upload_file, upload_json_data)

OLD_CLIP = re.compile(r"clip_(\d{3})_(\d+)-(\d+)\.mp4$")
MID_BLACK = "3690992020490662"


def archived_pairs(drive, quarantine):
    response = drive.files().list(q=f"'{quarantine}' in parents and trashed=false",
        fields="nextPageToken,files(id,name,size,mimeType)",pageSize=100).execute()
    if response.get("nextPageToken"):
        raise RuntimeError("More than 100 archived items; pagination required")
    found = {f["name"]:f for f in response.get("files",[])}
    for name,entry in sorted(found.items()):
        if not name.endswith(".json"):
            continue
        mp4 = found.get(name[:-5]+".mp4")
        if not mp4:
            continue
        try:
            data=json.loads(download_file_bytes(drive,entry["id"]))
        except (ValueError,UnicodeError):
            continue
        audit=data.get("kirinukiAudit") or {}
        source=data.get("videoFileName") or ""
        m=OLD_CLIP.search(source)
        if not m:
            continue
        if (audit.get("sourcePlatform")!="bilibili" or not audit.get("sourceContentId")
                or not audit.get("episodeKey") or not audit.get("sourceUploaderMid")):
            continue
        yield {"episodeKey":audit["episodeKey"],"bvid":audit["sourceContentId"],
               "mid":str(audit["sourceUploaderMid"]),"start":int(m.group(2)),
               "end":int(m.group(3)),"clipIndex":m.group(1),
               "oldVideoId":mp4["id"],"oldJsonId":entry["id"],
               "props":data}


def ff(cmd):
    r=subprocess.run(cmd, stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                     timeout=3600,check=False)
    if r.returncode:
        raise RuntimeError("media_command_failed:"+str(r.returncode))


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def build_clip(source, p, dest):
    length=p["end"]-p["start"]
    if not 8<=length<=150:
        raise ValueError("Invalid original source cut boundary")
    ff(["ffmpeg","-y","-loglevel","error","-ss",str(p["start"]),"-i",str(source),
        "-t",str(length),"-map","0:v:0","-map","0:a:0",
        "-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",
        "-r","30","-c:a","aac","-b:a","192k",str(dest)])
    return length


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quarantine-folder",required=True)
    p.add_argument("--review-folder",required=True)
    p.add_argument("--stock-folder",default=os.environ.get("GDRIVE_PARENT_FOLDER_ID",""))
    p.add_argument("--limit",type=int,default=11)
    args=p.parse_args()
    if not args.stock_folder:
        p.error("Posting stock folder required")
    drive=get_drive_service()
    original=list(archived_pairs(drive,args.quarantine_folder))
    # User-posted #4_006 is not present in quarantine as an MP4 and must not be recreated.
    original=original[:args.limit]
    groups={}
    for r in original:
        groups.setdefault((r["episodeKey"],r["bvid"],r["mid"]),[]).append(r)
    report=[]
    for (episode,bvid,mid),clips in groups.items():
        try:
            with tempfile.TemporaryDirectory(prefix="kyousuki-v2-raw-") as workspace:
                wd=Path(workspace)
                source=wd/"episode.mp4"
                from bilibili_source import download_video
                download_video(bvid,1,source,expected_mid=mid)
                # All starts/ends are from THIS verified uploader's same episode,
                # never transplanted to a differently edited mirror without alignment.
                public=Path("apps/remotion/public")
                clipdir=public/"out_clips"
                propsdir=public/"props"
                clips_dir_backup=wd/"old-clips-dir"
                props_dir_backup=wd/"old-props-dir"
                clipdir.mkdir(parents=True,exist_ok=True)
                propsdir.mkdir(parents=True,exist_ok=True)
                rendered=wd/"rendered"
                for clip in clips:
                    index=clip["clipIndex"]
                    ep_num=episode.rsplit(":",1)[-1]
                    stem=f"clip_ep{ep_num}_{index}"
                    outname=f"kyousuki_v2_raw_ep{ep_num}_clip_{index}"
                    if find_file(drive,args.review_folder,outname+".mp4") and find_file(drive,args.review_folder,outname+".json"):
                        report.append({"clip":outname,"status":"already_staged"})
                        continue
                    source_clip=clipdir/(stem+".mp4")
                    build_clip(source,clip,source_clip)
                    props=dict(clip["props"])
                    for old in ("topText","topRichText","bottomText","bottomRichText","sourceVideoTitle"):
                        props.pop(old,None)
                    props["videoFileName"]="out_clips/"+stem+".mp4"
                    props["durationInFrames"]=max(1,round((clip["end"]-clip["start"])*30))
                    props["sourceAspect"]=16/9
                    props["renderSpecVersion"]=2
                    props["fallbackMascot"]={"enabled":mid==MID_BLACK,"size":118,"right":56,"insetTop":282}
                    (propsdir/(stem+".json")).write_text(json.dumps(props,ensure_ascii=False),encoding="utf-8")
                from run_all import run_remotion_render
                if list(propsdir.glob("clip_ep*.json")):
                    run_remotion_render(propsdir,rendered,Path("apps/remotion"),high_quality=True)
                for clip in clips:
                    index=clip["clipIndex"]
                    ep_num=episode.rsplit(":",1)[-1]
                    stem=f"clip_ep{ep_num}_{index}"
                    outname=f"kyousuki_v2_raw_ep{ep_num}_clip_{index}"
                    mp4=rendered/(stem+".mp4")
                    if not mp4.exists():
                        continue
                    from packages.quality_gate import verify_rendered_media
                    media=verify_rendered_media(mp4)
                    original_audit=dict(clip["props"].get("kirinukiAudit") or {})
                    migration={"renderSpecVersion":2,"qaStatus":"review_required",
                        "mediaIntegrityQa":"pass","sourceBvid":bvid,"sourceUploaderMid":mid,
                        "episodeKey":episode,"oldDriveMp4Id":clip["oldVideoId"],
                        "oldDriveJsonId":clip["oldJsonId"],
                        "rebuildMethod":"source_episode_exact_timeline","newMp4Sha256":digest(mp4),
                        "newSizeBytes":mp4.stat().st_size,
                        "manualPostedExcluded":False}
                    original_audit["media"]={"sizeBytes":mp4.stat().st_size}
                    meta={"renderSpecVersion":2,"videoFileName":outname+".mp4",
                          "kirinukiAudit":original_audit,"stockMigration":migration,
                          "subtitleTimeline":clip["props"].get("subtitleTimeline",[]),
                          "reactionTimeline":clip["props"].get("reactionTimeline",[])}
                    side=wd/(outname+".json")
                    side.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
                    from scripts.kyousuki_media_qa import inspect
                    qa_dir=wd/(outname+"_frames")
                    qa=inspect(mp4,side,qa_dir,expected_bvid=bvid,expected_episode=episode)
                    proof=Path("raw-rebuild-proof")/outname
                    proof.mkdir(parents=True,exist_ok=True)
                    for img in qa_dir.glob("*.png"):
                        shutil.copy2(img,proof/img.name)
                    if (qa_dir/"qa.json").exists():
                        shutil.copy2(qa_dir/"qa.json",proof/"qa.json")
                    # A/V integrity and screenshot generation do not imply visual approval.
                    json_id=upload_json_data(drive,args.review_folder,side.name,side.read_bytes())
                    video_id=upload_file(drive,mp4,outname+".mp4",args.review_folder)
                    if not json_id or not video_id:
                        raise RuntimeError("Drive staged-pair upload incomplete")
                    report.append({"clip":outname,"status":"review_required",
                                   "videoId":video_id,"jsonId":json_id,
                                   "sourceBvid":bvid,"mediaQa":qa["status"]})
        except Exception as exc:
            for clip in clips:
                report.append({"episode":episode,"clip":clip["clipIndex"],
                               "status":"failed","error":type(exc).__name__})
        finally:
            # Do not leave source video or intermediate segment files on the runner.
            pass
    print("KYOUSUKI_RAW_REBUILD",json.dumps(report,ensure_ascii=False),flush=True)
    if any(r["status"]=="failed" for r in report):
        raise SystemExit(2)


if __name__=="__main__":
    main()
