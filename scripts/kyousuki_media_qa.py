"""Extract actual beginning/middle/end frames and fail-closed A/V and provenance QA.

This script produces evidence for visual human review; absence of OCR flags is
NOT proof that a logo, show title, or unauthorized source is absent.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path

OFFENDING = re.compile(r"bilibili|哔哩哔哩|黑田凖一|jeanne[_ ]?d[_ ]?arc|涟漪为谁|今天喜欢上你了", re.I)


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def probe(path):
    return json.loads(command("ffprobe", "-v", "error", "-show_format", "-show_streams",
                              "-of", "json", str(path)))


def frames(path, target, duration):
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for name, sec in zip(("beginning", "middle", "end"),(max(0.25,duration*0.1),
                           duration*0.5,max(0.25,duration*0.9))):
        out = target / (name+".png")
        command("ffmpeg", "-y", "-loglevel", "error", "-ss", str(sec), "-i", str(path),
                "-frames:v", "1", str(out))
        if not out.is_file() or out.stat().st_size < 500:
            raise RuntimeError("frame_extract_failed:"+name)
        saved.append({"atSeconds":round(sec,3),"path":out.name,"bytes":out.stat().st_size})
    return saved


def inspect(video, props, output, *, expected_bvid=None, expected_episode=None):
    info=probe(video)
    streams=info.get("streams") or []
    videos=[s for s in streams if s.get("codec_type")=="video"]
    audio=[s for s in streams if s.get("codec_type")=="audio"]
    dur=float((info.get("format") or {}).get("duration") or 0)
    result={"renderSpecVersion":2,"video":str(video),"durationSeconds":dur,
            "width":int(videos[0].get("width",0)) if videos else 0,
            "height":int(videos[0].get("height",0)) if videos else 0,
            "audioStreams":len(audio),"videoStreams":len(videos),
            "frames":[],"ocrFlags":[],"failures":[]}
    if not videos or not audio or dur<1:
        result["failures"].append("missing_video_audio_or_duration")
    if props:
        meta=json.loads(Path(props).read_text(encoding="utf-8"))
        audit=meta.get("kirinukiAudit") or {}
        result["bvid"]=audit.get("sourceContentId")
        result["episodeKey"]=audit.get("episodeKey")
        result["sourceUploaderMid"]=audit.get("sourceUploaderMid")
        result["rightsVerified"]=audit.get("permissionVerified") is True
        if expected_bvid and result["bvid"]!=expected_bvid:
            result["failures"].append("source_bvid_mismatch")
        if expected_episode and result["episodeKey"]!=expected_episode:
            result["failures"].append("episode_mismatch")
        if int(meta.get("renderSpecVersion") or 1) < 2:
            result["failures"].append("legacy_render_version")
        if not result["rightsVerified"]:
            result["failures"].append("source_permission_unverified")
        for sub in meta.get("subtitleTimeline") or []:
            if sub.get("startFrame", -1)<0 or sub.get("endFrame",0) <= sub.get("startFrame",0) or sub["endFrame"]>dur*30+2:
                result["failures"].append("invalid_subtitle_timestamp")
                break
    if videos and dur>=1:
        result["frames"]=frames(video,output,dur)
        # OCR is only a rejection signal, never an acceptance signal.
        for row in result["frames"]:
            img=output/row["path"]
            try:
                recognized=command("tesseract",str(img),"stdout","-l","eng+jpn+chi_sim")
                flags=OFFENDING.findall(recognized)
                if flags:
                    result["ocrFlags"].append({"frame":row["path"],"flags":list(set(flags))})
            except (OSError,subprocess.CalledProcessError):
                result["ocrUnavailable"]=True
                break
    if result["ocrFlags"]:
        result["failures"].append("title_or_repost_watermark_ocr")
    result["status"]="rejected" if result["failures"] else "visual_review_required"
    output.mkdir(parents=True,exist_ok=True)
    (output/"qa.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("video",type=Path)
    parser.add_argument("--props",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--expected-bvid")
    parser.add_argument("--expected-episode")
    args=parser.parse_args()
    result=inspect(args.video,args.props,args.out,
                   expected_bvid=args.expected_bvid,expected_episode=args.expected_episode)
    print(json.dumps(result,ensure_ascii=False))
    if result["status"]=="rejected":
        raise SystemExit(2)


if __name__=="__main__":
    main()
