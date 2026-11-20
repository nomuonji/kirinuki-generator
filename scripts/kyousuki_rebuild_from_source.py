"""Rebuild 11 quarantined Kyousuki clips from exact original source episodes.

Do not consult processed-episode stock-completion records: this is a versioned migration,
not normal stock production. Fail if missing originals, QA fails or staging is partial.
Final stock promotion is a separate review/verification step, never implicit.
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

from packages.shared.gdrive import get_drive_service, download_file_bytes, find_file, upload_file, upload_json_data
from packages.quality_gate import verify_rendered_media
from scripts.kyousuki_media_qa import inspect as inspect_media

OLD_CLIP = re.compile(r"clip_(\d{3})_(\d+)-(\d+)\.mp4$")
SOURCE_BLACK = "3690992020490662"
EXPECTED_SOURCE = {
    "2026:スウォン:2": ("BV1FNnZ6mEM3", SOURCE_BLACK),
    "2026:スウォン:3": ("BV1VX4P6qEwC", SOURCE_BLACK),
    "2026:スウォン:4": ("BV1DzW86hE4H", SOURCE_BLACK),
    "2026:スウォン:5": ("BV11GsK6RE2u", SOURCE_BLACK),
}

def run(command, timeout=1200):
    p = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"command exit {p.returncode}: {p.stderr[-600:]}")
    return p.stdout

def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", str(path)], timeout=60))

def digest(path):
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()

def archive_pairs(drive, folder):
    files = {}
    page = None
    while True:
        page_data=drive.files().list(q=f"'{folder}' in parents and trashed=false",
                    fields="nextPageToken,files(id,name,size,mimeType)",pageSize=100,pageToken=page).execute()
        files.update({f["name"]:f for f in page_data.get("files",[])})
        page=page_data.get("nextPageToken")
        if not page: break
    records=[]
    for name,item in sorted(files.items()):
        if not name.endswith(".json"): continue
        video=files.get(name[:-5]+".mp4")
        if not video: continue
        data=json.loads(download_file_bytes(drive,item["id"]))
        audit=data.get("kirinukiAudit") or {}
        bounds=OLD_CLIP.search(str(data.get("videoFileName") or ""))
        if not bounds: continue
        key=audit.get("episodeKey")
        if key not in EXPECTED_SOURCE: continue
        if (audit.get("sourceContentId"),str(audit.get("sourceUploaderMid"))) != EXPECTED_SOURCE[key]:
            raise RuntimeError("Legacy source/episode identity mismatch: "+name)
        start,end=int(bounds.group(2)),int(bounds.group(3))
        if start<0 or not 8<=end-start<=150:
            raise RuntimeError("Invalid clip timestamps: "+name)
        records.append({
            "episodeKey":key,"sourceBvid":audit["sourceContentId"],
            "sourceUploaderMid":str(audit["sourceUploaderMid"]),
            "startSeconds":start,"endSeconds":end,"index":bounds.group(1),
            "oldDriveMp4Id":video["id"],"oldDriveJsonId":item["id"],"data":data
        })
    return records

def make_cat(destination):
    """Opaque original loaf-cat, 320x96, covers only top-edge uploader mark."""
    from PIL import Image,ImageDraw
    out=Image.new("RGBA",(320,96),(0,0,0,0))
    dr=ImageDraw.Draw(out)
    border=(55,64,83,255)
    cream=(255,249,236,255)
    dr.rounded_rectangle((1,15,319,95),radius=38,fill=cream,outline=border,width=4)
    dr.ellipse((48,44,86,76),fill=(255,215,222,255))
    dr.ellipse((117,32,155,66),fill=(249,222,181,255))
    dr.polygon([(228,24),(244,0),(262,22)],fill=cream)
    dr.polygon([(285,23),(306,0),(312,32)],fill=cream)
    dr.polygon([(236,24),(247,9),(258,25)],fill=(255,174,189,255))
    dr.polygon([(290,24),(303,10),(306,30)],fill=(255,174,189,255))
    dr.ellipse((247,40,254,53),fill=border)
    dr.ellipse((287,40,294,53),fill=border)
    dr.ellipse((261,54,271,62),fill=(218,119,143,255))
    dr.arc((251,55,284,75),5,170,fill=border,width=3)
    dr.ellipse((225,56,240,68),fill=(255,172,190,200))
    dr.ellipse((299,56,313,68),fill=(255,172,190,200))
    dr.line([(81,77),(106,83),(128,76)],fill=border,width=3)
    out.save(destination)


def ass_time(seconds):
    cs=max(0,int(round(seconds*100)))
    h,rem=divmod(cs,360000)
    m,rem=divmod(rem,6000)
    s,cs=divmod(rem,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def ass_file(subtitles, seconds, path):
    head=(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,Noto Sans CJK JP,58,&H00FFFFFF,&H00FFFFFF,&H00121A21,&H88000000,-1,0,0,0,100,100,0,0,1,5,2,2,65,65,236,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    rows=[]
    for obj in subtitles:
        try:
            start=float(obj["startFrame"])/30
            end=float(obj["endFrame"])/30
        except (TypeError,KeyError,ValueError):
            continue
        end=min(end,seconds-0.03)
        if start<0 or end<=start: continue
        caption=str(obj.get("text") or "").strip()
        if not caption: continue
        # Strip potentially active ASS override markup rather than interpolating it.
        caption=caption.replace("{","(").replace("}",")").replace("\n",r"\N")
        rows.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{caption}")
    if not rows: raise RuntimeError("No reusable subtitles in archived clip")
    path.write_text(head+"\n".join(rows)+"\n",encoding="utf-8")
    return len(rows)

def render_episode_cut(source, mascot, record, destination, workdir):
    duration=record["endSeconds"]-record["startSeconds"]
    if duration<=0: raise ValueError("Invalid duration")
    subtitles=workdir/"subs.ass"
    count=ass_file(record["data"].get("subtitleTimeline") or [],duration,subtitles)
    stream=next((s for s in probe(source).get("streams",[]) if s.get("codec_type")=="video"),None)
    if stream is None: raise RuntimeError("Source video stream unavailable")
    iw,ih=int(stream.get("width") or 0),int(stream.get("height") or 0)
    if iw<640 or ih<360: raise RuntimeError("Source resolution too small")
    height=int(round((ih*1080/iw)/2)*2)
    top=int((1920-height)/2)-90
    if top<80: raise RuntimeError("Unsupported source aspect")
    # Blurred full-height fill eliminates black bars. Contained foreground preserves
    # multiple subjects and facial expressions, without the portrait centre-crop loss.
    watermark_fallback = record["sourceUploaderMid"] == SOURCE_BLACK
    base=(
       "[0:v]fps=30,split=2[a][b];"
       "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
       "boxblur=16:2,eq=brightness=-0.35[bg];"
       "[b]scale=1080:-2,setsar=1[fg];"
       f"[bg][fg]overlay=0:{top}:shortest=1[scene];"
    )
    if watermark_fallback:
        # The opaque cat's horizontal body hides the 320px-wide uploader
        # imprint only along the first 96px of the landscape scene. No faces
        # or subtitles are covered; no expensive per-frame inpainting.
        filters=base+(
          "[1:v]format=rgba[mascot];"
          f"[scene][mascot]overlay=W-w-2:{top}:shortest=1[decor];"
          f"[decor]ass=filename='{subtitles}'[v]"
        )
    else:
        filters=base+f"[scene]ass=filename='{subtitles}'[v]"
    cmd=["ffmpeg","-nostdin","-y","-loglevel","error",
         "-ss",str(record["startSeconds"]),"-i",str(source)]
    if record["sourceUploaderMid"]==SOURCE_BLACK:
        cmd+=["-loop","1","-framerate","30","-i",str(mascot)]
    cmd+=["-filter_complex",filters,"-map","[v]","-map","0:a:0",
          "-t",str(duration),"-r","30","-c:v","libx264","-preset","ultrafast",
          "-crf","19","-pix_fmt","yuv420p","-c:a","aac","-b:a","160k",
          "-movflags","+faststart",str(destination)]
    run(cmd,timeout=1800)
    return {"subtitleCount":count,"videoTop":top,"frameAspect":"9:16"}

def stage_clip(drive, review_folder, source, mascot, record, workdir):
    epno=record["episodeKey"].rsplit(":",1)[-1]
    stem=f"kyousuki_v2_ep{epno}_clip_{record['index']}"
    previous_video=find_file(drive,review_folder,stem+".mp4")
    previous_json=find_file(drive,review_folder,stem+".json")
    if previous_video or previous_json:
        if previous_video and previous_json:
            meta=json.loads(download_file_bytes(drive,previous_json["id"]))
            mig=meta.get("stockMigration") or {}
            if (mig.get("oldDriveMp4Id")==record["oldDriveMp4Id"] and
                    mig.get("oldDriveJsonId")==record["oldDriveJsonId"] and
                    mig.get("sourceBvid")==record["sourceBvid"]):
                return {"clip":stem,"status":"already_staged","mp4Id":previous_video["id"],
                        "jsonId":previous_json["id"]}
        raise RuntimeError("Incomplete or mismatched existing pair; manual reconciliation required")
    filename=workdir/(stem+".mp4")
    layout=render_episode_cut(source,mascot,record,filename,workdir)
    verify_rendered_media(filename)
    data=record["data"]
    audit=dict(data.get("kirinukiAudit") or {})
    hashed=digest(filename)
    actual=probe(filename)
    secs=float(actual["format"]["duration"])
    if not 9<=secs<151 or abs(secs-(record["endSeconds"]-record["startSeconds"]))>1.0:
        raise RuntimeError("Rendered media duration mismatch")
    audit["media"]={"sizeBytes":filename.stat().st_size,"durationSeconds":secs,
                    "width":1080,"height":1920}
    audit["publicationSha256"]=hashed
    editorial=re.sub(r"\*+","",str(data.get("topRichText") or "")).strip()
    audit["publicationTitle"]=f"今日好き｜韓国水原編 第{epno}話 {editorial}"[:95]
    audit["publicationDescription"]=(
        f"『今日、好きになりました。』韓国水原編・第{epno}話からの切り抜き。\n"
        f"出典：{audit.get('sourceVideoUrl') or 'Bilibili'}"
    )
    mig={"renderSpecVersion":2,"qaStatus":"review_required",
         "mediaIntegrityQa":"pass","sourceBvid":record["sourceBvid"],
         "sourceUploaderMid":record["sourceUploaderMid"],
         "episodeKey":record["episodeKey"],
         "oldDriveMp4Id":record["oldDriveMp4Id"],
         "oldDriveJsonId":record["oldDriveJsonId"],
         "cutStartSeconds":record["startSeconds"],"cutEndSeconds":record["endSeconds"],
         "rebuildMethod":"source_episode_ffmpeg_v4_catbadge_face_safe",
         "newMp4Sha256":hashed,"newSizeBytes":filename.stat().st_size,
         "fallbackMascot":record["sourceUploaderMid"]==SOURCE_BLACK,
         "manualPostedExcluded":False,"visualReviewEvidence":"raw-rebuild-proof/"+stem,
         "subtitleCount":layout["subtitleCount"]}
    # A v1 source cut may round up its final subtitle by a handful of frames.
    # Clamp the audit timeline to the actual re-rendered duration without
    # moving the start of a spoken line.
    timeline=[]
    last_frame=int(secs*30)
    for sub in data.get("subtitleTimeline") or []:
        clean=dict(sub)
        if int(clean.get("startFrame",0))>=last_frame: continue
        clean["endFrame"]=min(last_frame,int(clean.get("endFrame",last_frame)))
        if clean["endFrame"]>int(clean.get("startFrame",0)):
            timeline.append(clean)
    meta={"renderSpecVersion":2,"videoFileName":stem+".mp4",
          "kirinukiAudit":audit,"stockMigration":mig,
          "subtitleTimeline":timeline,
          "reactionTimeline":data.get("reactionTimeline") or []}
    side=workdir/(stem+".json")
    side.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    qa_dir=workdir/(stem+"_frames")
    qa=inspect_media(filename,side,qa_dir,expected_bvid=record["sourceBvid"],
                     expected_episode=record["episodeKey"])
    proof=Path("raw-rebuild-proof")/stem
    proof.mkdir(parents=True,exist_ok=True)
    for img in qa_dir.glob("*.png"): shutil.copy2(img,proof/img.name)
    shutil.copy2(qa_dir/"qa.json",proof/"qa.json")
    if qa["status"]=="rejected":
        raise RuntimeError("QA rejected "+stem+" "+str(qa.get("failures")))
    # Safe staged write: JSON first, MP4 second. Never publish or promote here.
    jsid=upload_json_data(drive,review_folder,side.name,side.read_bytes())
    vid=upload_file(drive,filename,filename.name,review_folder)
    if not jsid or not vid: raise RuntimeError("Incomplete staged Drive upload")
    return {"clip":stem,"status":"review_required","mp4Id":vid,"jsonId":jsid,
            "sourceBvid":record["sourceBvid"],"sha256":hashed,"qa":qa["status"],
            "subtitleCount":layout["subtitleCount"]}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quarantine-folder",required=True)
    ap.add_argument("--review-folder",required=True)
    ap.add_argument("--stock-folder",default=os.environ.get("GDRIVE_PARENT_FOLDER_ID",""))
    ap.add_argument("--limit",type=int,default=11)
    a=ap.parse_args()
    if not a.stock_folder: ap.error("--stock-folder required")
    drive=get_drive_service()
    records=archive_pairs(drive,a.quarantine_folder)
    if len(records)!=a.limit:
        raise RuntimeError(f"Expected exactly {a.limit} legacy unposted pairs, found {len(records)}")
    grouping={}
    for x in records: grouping.setdefault((x["episodeKey"],x["sourceBvid"],x["sourceUploaderMid"]),[]).append(x)
    results=[]
    cat_path=Path("raw-rebuild-proof")
    cat_path.mkdir(exist_ok=True)
    mascot=cat_path/"original_cat.png"
    make_cat(mascot)
    for (episode,bvid,mid),clips in grouping.items():
        try:
            with tempfile.TemporaryDirectory(prefix="kyousuki-source-v3-") as dirname:
                wd=Path(dirname)
                source=wd/"episode.mp4"
                from bilibili_source import download_video
                download_video(bvid,1,source,expected_mid=mid)
                video=next(s for s in probe(source)["streams"] if s["codec_type"]=="video")
                total=float(probe(source)["format"]["duration"])
                if total < max(c["endSeconds"] for c in clips)+1:
                    raise RuntimeError("Episode duration too short for archived timestamps")
                for clip in clips:
                    with tempfile.TemporaryDirectory(prefix="kyousuki-single-") as itemdir:
                        try:
                            row=stage_clip(drive,a.review_folder,source,mascot,clip,Path(itemdir))
                            results.append(row)
                            print("KYOUSUKI_STAGE",json.dumps(row,ensure_ascii=False),flush=True)
                        except Exception as exc:
                            failure={"episode":episode,"clip":clip["index"],
                                     "status":"failed","reason":str(exc)[:350]}
                            results.append(failure)
                            print("KYOUSUKI_STAGE_FAILURE",json.dumps(failure,ensure_ascii=False),flush=True)
        except Exception as exc:
            for clip in clips:
                if not any(x.get("clip")==clip["index"] and x.get("episode")==episode for x in results):
                    results.append({"episode":episode,"clip":clip["index"],
                                    "status":"failed","reason":str(exc)[:350]})
    summary={"expected":a.limit,"stagedOrExisting":sum(x["status"] in ("review_required","already_staged") for x in results),
             "failed":sum(x["status"]=="failed" for x in results),"items":results}
    Path("raw-rebuild-proof/summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("KYOUSUKI_RAW_REBUILD",json.dumps(summary,ensure_ascii=False),flush=True)
    if summary["stagedOrExisting"]!=a.limit or summary["failed"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
