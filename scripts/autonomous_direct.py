"""Zero-Drive happy-path Kirinuki: render to YouTube reservations, Drive on overflow.

This lane only activates after explicit source-rights + destination authorization.
All remote writes are journaled, and unknown upload outcomes are never blindly retried.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from packages.github_ledger import GitHubLedger
from packages.publish_scheduler import (aware, eligible_to_post, fingerprint,
                                        reserve_slots, rolling_uploads, utc_now)


def command(args, timeout=2400):
    print("Stage:", " ".join(str(a) for a in args), flush=True)
    subprocess.run(args, check=True, timeout=timeout)


def runtime():
    from packages.youtube_direct import auth_youtube, owned_videos, reservations
    yt, uploads = auth_youtube()
    actual = owned_videos(yt, uploads)
    return yt, actual, reservations(actual)


def reconcile(ledger, actual):
    """Known YouTube upload IDs and unique markers prevent blind duplicate retries."""
    from packages.youtube_direct import fingerprint_of
    by_key = {fingerprint_of(v): v for v in actual if fingerprint_of(v)}
    dirty = False
    for key, rec in ledger.data["clips"].items():
        remote = by_key.get(key)
        if remote:
            status = remote.get("status") or {}
            inferred = ("scheduled" if status.get("publishAt") else
                        "published" if status.get("privacyStatus") == "public" else
                        "uploaded_private_unscheduled")
            if rec.get("videoId") != remote["id"] or rec.get("status") not in ("scheduled", "published", "uploaded_private_unscheduled"):
                rec.update({"videoId": remote["id"],
                            "status": inferred,
                            "publishAt": status.get("publishAt"),
                            "privacyStatus": status.get("privacyStatus")})
                dirty = True
        elif rec.get("status") in ("uploading", "uncertain"):
            # A video can exist while absent from the most recent upload pages.
            # Never treat absence as proof that a retry is safe.
            rec["status"] = "uncertain"
            dirty = True
    if dirty:
        ledger.save()


def combined_reservations(ledger, provider):
    now = utc_now()
    merged = [r for r in provider if r.get("publishAt") and aware(r["publishAt"]) > now]
    keys = {(r.get("publishAt"), r.get("sourceVideoId")) for r in merged}
    for rec in ledger.data["clips"].values():
        if rec.get("status") not in ("scheduled", "verification_pending"):
            continue
        if (rec.get("publishAt") and aware(rec["publishAt"]) > now
                and (rec["publishAt"], rec.get("sourceVideoId")) not in keys):
            merged.append({"publishAt": rec["publishAt"], "sourceVideoId": rec.get("sourceVideoId")})
    return merged


def select_source(ledger):
    from youtube_watcher import (get_uploads_playlist_id, fetch_recent_videos,
                                 build_ranked_candidates)
    from packages.operations import OperationsConfig
    key = os.environ.get("YOUTUBE_API_KEY")
    channel = os.environ.get("YOUTUBE_CHANNEL_ID")
    if not key or not channel:
        raise RuntimeError("Source YouTube API key / channel ID is missing")
    config = OperationsConfig.from_env()
    playlist = get_uploads_playlist_id(key, channel)
    if not playlist:
        raise RuntimeError("Cannot resolve source channel")
    videos = fetch_recent_videos(key, playlist, config.max_search_videos)
    now = utc_now()
    ignored = set()
    for vid, record in ledger.data["sources"].items():
        status = record.get("status")
        last = record.get("attemptedAt")
        if status == "completed":
            ignored.add(vid)
        elif status in ("processing", "failed", "partial") and last:
            try:
                if now - aware(last) < timedelta(hours=6):
                    ignored.add(vid)
            except ValueError:
                ignored.add(vid)
    ranked = build_ranked_candidates(videos, ignored, config)
    if not ranked and config.fallback_max_source_age_days > config.max_source_age_days:
        videos = fetch_recent_videos(key, playlist, config.fallback_max_search_videos)
        ranked = build_ranked_candidates(
            videos, ignored, config,
            max_source_age_days=config.fallback_max_source_age_days,
            max_source_duration_minutes=config.fallback_max_source_duration_minutes,
        )
    return next((v for v in ranked if float(v.get("selectionScore", 0)) >= config.min_selection_score), None)


class DirectLane:
    def __init__(self):
        self.lane = os.environ.get("KIRINUKI_LANE", "hiroyuki-official")
        self.ledger = GitHubLedger(self.lane)
        self.ledger.load()
        self.youtube, self.actual, self.provider_slots = runtime()
        reconcile(self.ledger, self.actual)
        self.now = utc_now()
        self.max_uploads_per_24h = max(1, int(os.environ.get("KIRINUKI_UPLOADS_PER_24H", "6")))
        self.max_clips_per_run = max(1, min(12, int(os.environ.get("KIRINUKI_CLIPS_PER_RUN", "6"))))
        self.target_reservations = max(1, int(os.environ.get("KIRINUKI_TARGET_RESERVATIONS", "14")))
        self.window_days = max(1, min(28, int(os.environ.get("KIRINUKI_RESERVATION_DAYS", "14"))))
        self.uploaded_this_run = 0

    def reservation_entries(self):
        return combined_reservations(self.ledger, self.provider_slots)

    def available_capacity(self):
        from packages.youtube_direct import fingerprint_of
        known = [r for r in self.ledger.data["clips"].values()
                 if r.get("uploadedAt") and r.get("videoId")]
        # Count authenticated destination uploads as well, including non-Kirinuki.
        seen = {r.get("videoId") for r in known}
        for video in self.actual:
            v_id = video.get("id")
            if v_id in seen:
                continue
            published_at = (video.get("snippet") or {}).get("publishedAt")
            if published_at:
                known.append({"uploadedAt": published_at})
        return max(0, self.max_uploads_per_24h - rolling_uploads(known, now=self.now))

    def next_slot(self, source_id):
        entries = self.reservation_entries()
        if len(entries) >= self.target_reservations:
            return None
        found = reserve_slots(entries, now=self.now, days=self.window_days,
                              max_count=1, source_id=source_id)
        return found[0] if found else None

    def publish(self, path, item):
        from packages.youtube_direct import (UploadDeferred, UploadUncertain, upload_once,
                                              readback_video, fingerprint_of)
        key = item["fingerprint"]
        old = self.ledger.clip(key)
        if old and old.get("status") in ("scheduled", "published", "verification_pending",
                                        "uploading", "uncertain", "uploaded_private_unscheduled"):
            print(f"Already handled or unresolved: {key}, {old['status']}")
            return "already_handled"
        # Re-runs with slightly shifted timestamps must not create overlapping
        # duplicate clips from the same long-form source.
        start, end = float(item.get("start", -1)), float(item.get("end", -1))
        if end > start >= 0:
            for other_key, other in self.ledger.data["clips"].items():
                if other_key == key or other.get("sourceVideoId") != item["sourceVideoId"]:
                    continue
                if other.get("status") not in (
                    "scheduled", "published", "verification_pending", "uploading",
                    "uncertain", "overflow", "uploaded_private_unscheduled",
                ):
                    continue
                a, b = float(other.get("start", -1)), float(other.get("end", -1))
                if b > a >= 0 and max(0.0, min(end, b)-max(start, a)) >= 0.75 * min(end-start, b-a):
                    print(f"Skipping substantial same-source duplicate of {other_key}")
                    return "already_handled"
        if self.available_capacity() == 0:
            return "overflow"
        slot = self.next_slot(item["sourceVideoId"])
        if slot is None:
            return "overflow"
        self.ledger.set_clip(key, **item, status="uploading",
                             attemptedAt=utc_now().isoformat(), publishAt=slot)
        try:
            receipt = upload_once(
                self.youtube, path, title=item["title"],
                description=item.get("description", ""),
                source_video_id=item["sourceVideoId"], fingerprint=key, publish_at=slot)
        except UploadDeferred as exc:
            print(f"Confirmed channel/API capacity rejection for {key}: {exc}")
            self.max_uploads_per_24h = 0  # stop attempting uploads in this run
            self.ledger.set_clip(
                key, **item, status="overflow" if old and old.get("driveVideoId")
                else "overflow_pending", failure="upload_capacity"
            )
            return "overflow"
        except UploadUncertain as exc:
            print(f"Ambiguous upload outcome for {key}: {exc}")
            self.ledger.set_clip(key, **item, status="uncertain", failure="unknown_upload_result")
            return "uncertain"

        self.uploaded_this_run += 1
        self.ledger.set_clip(key, **item, status="verification_pending", **receipt)
        try:
            remote = readback_video(self.youtube, receipt["videoId"])
            if (remote and (remote.get("status") or {}).get("privacyStatus") == "private"
                    and (remote.get("status") or {}).get("publishAt")):
                self.ledger.set_clip(key, status="scheduled",
                                     privacyStatus="private",
                                     publishAt=remote["status"]["publishAt"])
                self.provider_slots.append({"publishAt": remote["status"]["publishAt"],
                                            "sourceVideoId": item["sourceVideoId"]})
                self.actual.append(remote)
                return "scheduled"
        except Exception as exc:
            print(f"Readback pending for {key}: {type(exc).__name__}")
        # A successful video ID must never be uploaded a second time.
        self.provider_slots.append({"publishAt": slot, "sourceVideoId": item["sourceVideoId"]})
        return "verification_pending"

    def overflow(self, video_path, item):
        """Write metadata before MP4 so a partial fallback is not mistaken for ready stock."""
        from packages.shared.gdrive import (find_file, get_drive_service,
                                             upload_file, upload_json_data)
        folder = os.environ.get("GDRIVE_PARENT_FOLDER_ID")
        if not folder:
            self.ledger.set_clip(item["fingerprint"], **item,
                                 status="regeneration_needed", failure="no_overflow_drive")
            raise RuntimeError("No overflow Drive folder configured; clip remains regeneration_needed")
        service = get_drive_service()
        key = item["fingerprint"]
        base = f"overflow_{key}_clip_001"
        meta_name = f"{base}.json"
        video_name = f"{base}.mp4"
        props = json.dumps(item, ensure_ascii=False, indent=2).encode("utf-8")
        metadata = find_file(service, folder, meta_name)
        m_id = upload_json_data(service, folder, meta_name, props, metadata["id"] if metadata else None)
        prior = find_file(service, folder, video_name)
        v_id = prior["id"] if prior else upload_file(service, Path(video_path), video_name, folder)
        if not m_id or not v_id:
            self.ledger.set_clip(key, **item, status="regeneration_needed", failure="drive_fallback_failed")
            raise RuntimeError("Overflow Drive upload did not return IDs")
        self.ledger.set_clip(key, **item, status="overflow", driveVideoId=v_id,
                             driveMetadataId=m_id, fallbackAt=utc_now().isoformat())
        print(f"Deferred {key} to Drive (metadata+MP4).")

    def replay_overflow(self):
        from packages.shared.gdrive import (delete_file, download_file_bytes, get_drive_service)
        records = [(k, r) for k, r in self.ledger.data["clips"].items()
                   if r.get("status") == "overflow" and r.get("driveVideoId")]
        if not records or not self.next_slot(records[0][1]["sourceVideoId"]):
            return
        service = get_drive_service()
        for key, recorded in records:
            if self.available_capacity() <= 0 or not self.next_slot(recorded["sourceVideoId"]):
                break
            raw = download_file_bytes(service, recorded["driveVideoId"])
            # The stored journal contains lifecycle keys. Do not pass them as
            # fresh publishing arguments or override the reserved status.
            item = {k: recorded[k] for k in (
                "fingerprint", "title", "sourceVideoId", "sourceChannelId",
                "start", "end", "confidence", "mediaAudit", "editorialDigest",
                "description"
            ) if k in recorded}
            with tempfile.TemporaryDirectory(prefix="kirinuki-overflow-") as tmp:
                path = Path(tmp) / "video.mp4"
                path.write_bytes(raw)
                disposition = self.publish(path, item)
            if disposition in ("scheduled", "verification_pending"):
                delete_file(service, recorded["driveVideoId"])
                if recorded.get("driveMetadataId"):
                    delete_file(service, recorded["driveMetadataId"])
            if disposition in ("overflow", "uncertain"):
                break

    def plan(self):
        backlog = sum(1 for r in self.ledger.data["clips"].values()
                      if r.get("status") == "overflow")
        reserved = len(self.reservation_entries())
        capacity = self.available_capacity()
        has_slot = bool(self.next_slot("__probe__"))
        source = select_source(self.ledger) if has_slot and capacity > 0 and reserved < self.target_reservations else None
        needed = (backlog > 0 or source is not None) and capacity > 0 and has_slot
        return {"shouldProcess": bool(needed), "sourceVideoId": source["videoId"] if source else None,
                "scheduledStock": reserved, "targetStock": self.target_reservations,
                "remaining24hCapacity": capacity, "overflowCount": backlog,
                "sourceSelectionScore": round(source.get("selectionScore", 0), 3) if source else None}

    def produce(self, source):
        from packages.quality_gate import (AUDIT_FILENAME, validated_receipt, verify_rendered_media)
        from run_all import run_remotion_render
        source_id = source["videoId"]
        self.ledger.set_source(source_id, status="processing", attemptedAt=utc_now().isoformat(),
                               title=source["title"])
        source_title = str(source["title"])
        os.environ["SOURCE_VIDEO_TITLE"] = source_title
        os.environ["SOURCE_VIDEO_PUBLISHED_AT"] = source.get("publishedAt") or ""
        tmp = Path("tmp")
        tmp.mkdir(exist_ok=True)
        video = tmp / "direct_source.mp4"
        transcript = tmp / "direct_transcript.json"
        clip_dir = Path("apps/remotion/public/out_clips")
        props_dir = Path("apps/remotion/public/props")
        rendered = Path("direct_rendered")
        for directory in (clip_dir, props_dir, rendered):
            if directory.exists():
                import shutil
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
        command([sys.executable, "download_video.py", source_id, "--output", str(video)], timeout=3300)
        command([sys.executable, "transcribe_rapidapi.py", source_id,
                 "--output", str(transcript)], timeout=1200)
        concept = os.environ.get("KIRINUKI_CONCEPT_FILE", "configs/video_concept_hiroyuki.md")
        target = min(self.max_clips_per_run, self.target_reservations)
        command([sys.executable, "-m", "apps.cli.generate_clips",
                 "--video", str(video), "--transcript", str(transcript),
                 "--out", str(clip_dir), "--subs", "--concept-file", concept,
                 "--max-clips", str(target)], timeout=3200)
        if not validated_receipt(clip_dir):
            raise RuntimeError("The independent QA receipt was not created")
        candidates = json.loads((clip_dir / "clip_candidates.json").read_text(encoding="utf-8"))
        if not candidates:
            raise RuntimeError("No approved clip candidates")
        command([sys.executable, "-m", "apps.cli.generate_reactions",
                 "--transcript", str(transcript),
                 "--clip-candidates", str(clip_dir / "clip_candidates.json"),
                 "--output-dir", str(clip_dir), "--max-reactions", "3"],
                timeout=1400)
        command([sys.executable, "-m", "apps.cli.render_clips", "--input-dir", str(clip_dir)],
                timeout=1900)
        if not list(props_dir.glob("clip_*.json")):
            raise RuntimeError("No Remotion props were produced")
        audit = json.loads((clip_dir / AUDIT_FILENAME).read_text(encoding="utf-8"))
        outcomes = []
        def on_rendered(prop_path, mp4_path):
            match = re.search(r"clip_(\d+)", prop_path.name)
            if not match:
                raise RuntimeError("Cannot pair rendered MP4 and editorial metadata")
            idx = int(match.group(1))-1
            if idx < 0 or idx >= len(candidates):
                raise RuntimeError("Rendered clip index outside approved candidates")
            candidate = candidates[idx]
            qa = verify_rendered_media(mp4_path)
            key = fingerprint(source_id, candidate["start"], candidate["end"], version="direct-v1")
            title = str(candidate.get("title") or source_title).replace("**", "")
            item = {
                "fingerprint": key, "title": title[:98], "sourceVideoId": source_id,
                "sourceChannelId": os.environ.get("YOUTUBE_CHANNEL_ID", ""),
                "start": candidate["start"], "end": candidate["end"],
                "confidence": candidate.get("confidence"), "mediaAudit": qa,
                "editorialDigest": audit["candidateDigest"],
                "description": "AIによる文脈整理付きの切り抜き。元動画の発言を独立した話として収録しています。",
            }
            disposition = self.publish(mp4_path, item)
            if disposition == "overflow":
                self.overflow(mp4_path, item)
            elif disposition == "uncertain":
                # Preserve bytes for a future reconciliation, never blind-retry.
                self.overflow(mp4_path, item)
                self.ledger.set_clip(key, status="uncertain", failure="needs_provider_reconciliation")
            outcomes.append({"key": key, "status": disposition})
            Path(mp4_path).unlink(missing_ok=True)
        run_remotion_render(props_dir, rendered, Path("apps/remotion"),
                           on_clip_rendered=on_rendered)
        if not outcomes:
            raise RuntimeError("No reviewed clips were rendered")
        self.ledger.set_source(source_id, status="completed",
                               completedAt=utc_now().isoformat(),
                               outcomes=outcomes)
        return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--plan-output", default="direct-plan.json")
    args = parser.parse_args()
    enabled, why = eligible_to_post(os.environ)
    if not enabled:
        result = {"shouldProcess": False, "mode": why}
        Path(args.plan_output).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return
    lane = DirectLane()
    plan = lane.plan()
    Path(args.plan_output).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if args.plan_only or not plan["shouldProcess"]:
        return
    lane.replay_overflow()
    plan = lane.plan()
    if not plan["shouldProcess"] or not plan["sourceVideoId"]:
        return
    source = select_source(lane.ledger)
    if not source:
        return
    try:
        result = lane.produce(source)
        print("Production result:", json.dumps(result, ensure_ascii=False))
    except Exception:
        lane.ledger.set_source(source["videoId"], status="failed",
                               attemptedAt=utc_now().isoformat())
        raise


if __name__ == "__main__":
    main()
