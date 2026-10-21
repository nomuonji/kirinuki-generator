"""End-to-end *local-only* production smoke, no YouTube publication or Drive.

Uses the same production code to fetch, transcribe, select, independently
review, cut, render and decode one clip. Publishes no content whatsoever.
"""
from __future__ import annotations
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from scripts.autonomous_direct import DirectLane


class LocalJournal:
    def __init__(self):
        self.data = {"sources": {}, "clips": {}}

    def set_source(self, video_id, **fields):
        source = self.data["sources"].setdefault(video_id, {})
        source.update(fields)
        return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output-dir", default="private-smoke-results")
    args = parser.parse_args()
    if len(args.video_id) != 11 or not all(c.isalnum() or c in "_-" for c in args.video_id):
        parser.error("--video-id must be a YouTube ID")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    lane = DirectLane.__new__(DirectLane)
    lane.ledger = LocalJournal()
    lane.max_clips_per_run = 1
    lane.target_reservations = 1
    rendered = []

    def preview_only(video_path, item):
        if rendered:
            raise RuntimeError("Smoke test must render exactly one clip")
        target = out / "private_preview.mp4"
        shutil.copy2(video_path, target)
        rendered.append({
            "sourceVideoId": item["sourceVideoId"],
            "clipStart": item["start"],
            "clipEnd": item["end"],
            "renderedBytes": target.stat().st_size,
            "mediaAudit": item["mediaAudit"],
            "editorialDigest": item["editorialDigest"],
            "status": "preview_only_not_uploaded",
        })
        return "preview_only"

    lane.publish = preview_only
    report = {"startedAt": datetime.now(timezone.utc).isoformat(),
              "sourceVideoId": args.video_id, "publicationAttempted": False}
    try:
        outcome = lane.produce({
            "videoId": args.video_id,
            "title": f"Private pipeline smoke source {args.video_id}",
            "publishedAt": "",
        })
        if len(rendered) != 1 or len(outcome) != 1:
            raise RuntimeError("Expected exactly one verified private output")
        report["result"] = "PASS"
        report["rendered"] = rendered
    except Exception as exc:
        report["result"] = "FAIL"
        report["reasonType"] = type(exc).__name__
        raise
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("SMOKE_REPORT=" + json.dumps({
            k:v for k,v in report.items() if k != "rendered"}, ensure_ascii=False))
    print("PRIVATE RENDER VERIFIED. NO YOUTUBE OR DRIVE UPLOAD WAS ATTEMPTED.")


if __name__ == "__main__":
    main()
