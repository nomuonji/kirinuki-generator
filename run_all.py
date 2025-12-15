import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from packages.cutter_ffmpeg.cutter import ClipSpec, cut_many
from datetime import timedelta
from packages.shared.gdrive import (
    build_safe_filename,
    download_file_bytes,
    find_file,
    get_drive_service,
    list_state_files,
    sanitize_filename,
    upload_file,
    upload_json_data,
    delete_file,
)
MAX_CLIPS_PER_BATCH = 15
CLIP_FILENAME_PATTERN = re.compile(r"clip_(\d{3})", re.IGNORECASE)
STATE_FILE_TEMPLATE = "state_{video_id}.json"
RENDERED_CLIP_PATTERN = re.compile(r"clip_(\d{3})(?:[_-].*)?\.mp4$", re.IGNORECASE)
PROPS_FILENAME_PATTERN = re.compile(r"clip_(\d{3})(?:[_-].*)?\.json$", re.IGNORECASE)

# Rate limit error patterns to detect 429 errors from subprocesses
RATE_LIMIT_PATTERNS = [
    "429",
    "ResourceExhausted",
    "exceeded your current quota",
    "rate limit",
    "too many requests",
]

class RateLimitError(Exception):
    """Raised when a rate limit (429) error is detected from a subprocess."""
    pass

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def load_state_from_drive(service, parent_folder_id: str, video_id: str) -> tuple[dict, str, str | None]:
    """Loads state.json for the given video from Google Drive, if it exists."""
    state_file_name = STATE_FILE_TEMPLATE.format(video_id=video_id)
    state_file = find_file(service, parent_folder_id, state_file_name)
    if not state_file:
        return {}, state_file_name, None
    try:
        payload = download_file_bytes(service, state_file["id"])
        return json.loads(payload.decode("utf-8")), state_file_name, state_file["id"]
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Failed to parse state file from Drive ({state_file_name}): {exc}", file=sys.stderr)
        return {}, state_file_name, state_file["id"]

def save_state_to_drive(service, parent_folder_id: str, state_file_name: str, state: dict, file_id: str | None) -> str:
    """Persists the state JSON to Google Drive, creating or updating the file."""
    state["lastUpdated"] = _utc_now_iso()
    payload = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
    return upload_json_data(service, parent_folder_id, state_file_name, payload, file_id)


def cleanup_old_state_files(
    service,
    parent_folder_id: str,
    current_video_id: str,
    max_age_days: int = 7,
) -> int:
    """
    Remove old state files from Google Drive.
    
    Deletes state files that are:
    - Older than max_age_days (based on modifiedTime)
    - Not the current video being processed
    
    Returns the number of files deleted.
    """
    try:
        state_files = list_state_files(service, parent_folder_id)
    except Exception as exc:
        print(f"Warning: Failed to list state files for cleanup: {exc}", file=sys.stderr)
        return 0
    
    if not state_files:
        return 0
    
    current_state_name = STATE_FILE_TEMPLATE.format(video_id=current_video_id)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    deleted_count = 0
    
    for file_info in state_files:
        file_name = file_info.get("name", "")
        file_id = file_info.get("id")
        modified_time_str = file_info.get("modifiedTime", "")
        
        # Skip the current video's state file
        if file_name == current_state_name:
            continue
        
        # Only delete files older than the cutoff
        try:
            # Parse ISO 8601 timestamp (e.g., "2025-01-01T12:00:00.000Z")
            modified_time = datetime.fromisoformat(modified_time_str.replace("Z", "+00:00"))
            if modified_time > cutoff:
                continue  # File is still fresh, keep it
        except (ValueError, TypeError):
            # If we can't parse the timestamp, skip deletion to be safe
            continue
        
        # Try to check if the state is "failed" before deleting
        # This adds safety but costs an extra API call per file
        try:
            payload = download_file_bytes(service, file_id)
            state_data = json.loads(payload.decode("utf-8"))
            status = state_data.get("status", "")
            
            # Delete only if status is 'failed' or 'completed' (completed should already be gone, but just in case)
            if status not in ("failed", "completed"):
                # Still in-progress, might be from a concurrent run, skip
                continue
        except Exception:
            # If we can't read the file, it might be corrupted - safe to delete
            pass
        
        # Delete the old state file
        try:
            delete_file(service, file_id)
            print(f"  -> Cleaned up old state file: {file_name}")
            deleted_count += 1
        except Exception as exc:
            print(f"Warning: Failed to delete old state file {file_name}: {exc}", file=sys.stderr)
    
    return deleted_count

def load_clips_manifest_from_drive(service, artifact_info: dict) -> dict | None:
    """Load the stored clips manifest JSON from Drive."""
    file_id = artifact_info.get("fileId") if artifact_info else None
    if not file_id:
        return None
    try:
        payload = download_file_bytes(service, file_id)
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Failed to load clips manifest from Drive: {exc}", file=sys.stderr)
        return None

def find_rendered_clip_file(output_dir: Path, clip_key: str) -> Path | None:
    """Locate the rendered clip file for the given clip key, accommodating timestamp suffixes."""
    pattern_glob = f"clip_{clip_key}*.mp4"
    candidates = sorted(output_dir.glob(pattern_glob))
    for candidate in candidates:
        match = RENDERED_CLIP_PATTERN.fullmatch(candidate.name)
        if match and match.group(1) == clip_key:
            return candidate
    legacy = output_dir / f"clip_{clip_key}.mp4"
    return legacy if legacy.exists() else None

def find_props_file(props_dir: Path, clip_key: str) -> Path | None:
    """Locate the props JSON file for the given clip key."""
    pattern_glob = f"clip_{clip_key}*.json"
    candidates = sorted(props_dir.glob(pattern_glob))
    for candidate in candidates:
        match = PROPS_FILENAME_PATTERN.fullmatch(candidate.name)
        if match and match.group(1) == clip_key:
            return candidate
    legacy = props_dir / f"clip_{clip_key}.json"
    return legacy if legacy.exists() else None
def build_clips_manifest(clips_dir: Path) -> dict | None:
    """Construct a manifest capturing clip metadata for deterministic regeneration."""
    candidates_path = clips_dir / "clip_candidates.json"
    if not candidates_path.exists():
        return None

    try:
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Warning: Failed to parse clip_candidates.json: {exc}", file=sys.stderr)
        return None

    manifest: dict[str, object] = {
        "version": 1,
        "generatedAt": _utc_now_iso(),
        "candidates": candidates,
        "clips": {},
    }

    for idx, candidate in enumerate(candidates, start=1):
        clip_key = f"{idx:03d}"
        clip_entry = {
            "start": float(candidate.get("start", 0.0)),
            "end": float(candidate.get("end", 0.0)),
            "title": candidate.get("title", ""),
            "punchline": candidate.get("punchline", ""),
            "reason": candidate.get("reason", ""),
            "confidence": candidate.get("confidence", 0.0),
        }

        hooks_path = clips_dir / f"clip_{clip_key}_hooks.txt"
        if hooks_path.exists():
            try:
                clip_entry["hooks"] = json.loads(hooks_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                clip_entry["hooksText"] = hooks_path.read_text(encoding="utf-8")

        details_path = clips_dir / f"clip_{clip_key}_details.txt"
        if details_path.exists():
            clip_entry["details"] = details_path.read_text(encoding="utf-8")

        subtitles_path = clips_dir / f"clip_{clip_key}_subtitles.json"
        if subtitles_path.exists():
            try:
                clip_entry["subtitles"] = json.loads(subtitles_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                clip_entry["subtitlesText"] = subtitles_path.read_text(encoding="utf-8")

        reactions_path = clips_dir / f"clip_{clip_key}_reactions.json"
        if reactions_path.exists():
            try:
                clip_entry["reactions"] = json.loads(reactions_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                clip_entry["reactionsText"] = reactions_path.read_text(encoding="utf-8")

        manifest["clips"][clip_key] = clip_entry

    return manifest

def restore_clips_from_manifest(manifest: dict, video_path: Path, clips_dir: Path) -> bool:
    """Recreate clip assets from a stored manifest and fresh cuts."""
    candidates = manifest.get("candidates")
    clips_meta: dict = manifest.get("clips", {})
    if not candidates or not isinstance(candidates, list):
        return False

    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)

    candidates_path = clips_dir / "clip_candidates.json"
    candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    clip_specs: list[ClipSpec] = []

    for idx, candidate in enumerate(candidates, start=1):
        clip_key = f"{idx:03d}"
        clip_data = clips_meta.get(clip_key, {})

        start = float(clip_data.get("start", candidate.get("start", 0.0)))
        end = float(clip_data.get("end", candidate.get("end", start)))
        title = clip_data.get("title") or candidate.get("title", "")

        clip_specs.append(ClipSpec(start=start, end=end, index=idx, title=title))

        hooks = clip_data.get("hooks")
        hooks_text = clip_data.get("hooksText")
        hooks_path = clips_dir / f"clip_{clip_key}_hooks.txt"
        if hooks:
            hooks_path.write_text(json.dumps(hooks, ensure_ascii=False, indent=2), encoding="utf-8")
        elif hooks_text:
            hooks_path.write_text(hooks_text, encoding="utf-8")

        details_text = clip_data.get("details")
        if details_text:
            (clips_dir / f"clip_{clip_key}_details.txt").write_text(details_text, encoding="utf-8")

        subtitles = clip_data.get("subtitles")
        subtitles_text = clip_data.get("subtitlesText")
        subtitles_path = clips_dir / f"clip_{clip_key}_subtitles.json"
        if subtitles is not None:
            subtitles_path.write_text(json.dumps(subtitles, ensure_ascii=False, indent=2), encoding="utf-8")
        elif subtitles_text:
            subtitles_path.write_text(subtitles_text, encoding="utf-8")

        reactions = clip_data.get("reactions")
        reactions_text = clip_data.get("reactionsText")
        reactions_path = clips_dir / f"clip_{clip_key}_reactions.json"
        if reactions is not None:
            reactions_path.write_text(json.dumps(reactions, ensure_ascii=False, indent=2), encoding="utf-8")
        elif reactions_text:
            reactions_path.write_text(reactions_text, encoding="utf-8")

    cut_many(str(video_path), clip_specs, str(clips_dir), quiet=True)
    return True

def upload_clip_and_props(
    clip_key: str,
    rendered_file: Path,
    prop_file: Path | None,
    sanitized_title: str,
    drive_service,
    drive_parent_id: str,
    clips_state: dict,
    batch_idx: int,
    persist_state_fn,
):
    remote_base = build_safe_filename(sanitized_title, f"_clip_{clip_key}")
    remote_name = f"{remote_base}.mp4"
    file_size = rendered_file.stat().st_size
    print(f"Uploading clip {clip_key} ({rendered_file.name}) to Drive as {remote_name}...")
    file_id = upload_file(drive_service, rendered_file, remote_name, drive_parent_id)
    if not file_id:
        raise RuntimeError(f"Drive upload did not return a file ID for {remote_name}")
    print(f"  -> Drive upload succeeded for clip {clip_key}: id={file_id}, size={file_size} bytes")

    clip_record = clips_state.setdefault(clip_key, {})
    clip_record["rendered"] = True
    clip_record["uploaded"] = True
    clip_record["batchIndex"] = batch_idx
    clip_record["driveFileId"] = file_id
    clip_record["remoteFileName"] = remote_name
    clip_record["uploadedAt"] = _utc_now_iso()
    clip_record["sizeBytes"] = file_size
    persist_state_fn()

    if prop_file and prop_file.exists():
        props_remote_name = f"{remote_base}.json"
        print(f"Uploading props for clip {clip_key} ({prop_file.name}) to Drive as {props_remote_name}...")
        props_payload = prop_file.read_bytes()
        props_file_id = upload_json_data(
            drive_service,
            drive_parent_id,
            props_remote_name,
            props_payload,
            clip_record.get("propsDriveFileId"),
        )
        clip_record["propsDriveFileId"] = props_file_id
        clip_record["propsRemoteFileName"] = props_remote_name
        clip_record["propsUploadedAt"] = _utc_now_iso()
        persist_state_fn()
        print(f"  -> Drive upload succeeded for props {clip_key}: id={props_file_id}, size={len(props_payload)} bytes")
    else:
        print(f"Warning: Props file not found for clip {clip_key}; skipping props upload.", file=sys.stderr)

    try:
        rendered_file.unlink()
    except OSError:
        print(f"Warning: Could not delete local clip {rendered_file}", file=sys.stderr)

def run_command(command, description, cwd=None, quiet=False):
    """Runs a command, optionally silencing real-time output."""
    print(f"--- {description} ---")
    cmd_str = ' '.join(map(str, command))
    print(f"Executing: {cmd_str}")

    try:
        if quiet:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                cwd=cwd,
            )
            if result.returncode != 0:
                if result.stdout:
                    print(result.stdout, file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                raise subprocess.CalledProcessError(result.returncode, command)
        else:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                cwd=cwd
            )

            captured_output = []
            for line in iter(process.stdout.readline, ''):
                print(line, end='')
                captured_output.append(line)

            process.stdout.close()
            return_code = process.wait()

            if return_code != 0:
                # Check if this is a rate limit error
                full_output = ''.join(captured_output)
                for pattern in RATE_LIMIT_PATTERNS:
                    if pattern.lower() in full_output.lower():
                        raise RateLimitError(f"Rate limit detected in '{description}': {pattern}")
                raise subprocess.CalledProcessError(return_code, command)

        print(f"\n--- Finished: {description} ---\n")

    except subprocess.CalledProcessError as e:
        print(f"\nERROR during '{description}': Command returned non-zero exit status {e.returncode}.", file=sys.stderr)
        raise e
    except FileNotFoundError:
        print(f"\nERROR: Command not found for '{description}': {command[0]}", file=sys.stderr)
        raise
def probe_video_duration(video_path: Path) -> float:
    """Returns the duration of the downloaded video in seconds (0.0 if unknown)."""
    if not video_path.exists():
        return 0.0

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="ignore",
            text=True,
        )
        value = result.stdout.strip()
        return float(value) if value else 0.0
    except FileNotFoundError:
        print("Warning: ffprobe not found; skipping duration-based batching.", file=sys.stderr)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Warning: Failed to probe video duration ({exc}).", file=sys.stderr)
    return 0.0

def determine_batch_count(duration_sec: float) -> int:
    """Determines how many processing batches to run based on video length."""
    if duration_sec > 2 * 3600:
        return 3
    if duration_sec > 3600:
        return 2
    return 1

def collect_clip_indices(clips_dir: Path) -> list[int]:
    """Collects integer clip indices from generated clip files."""
    indices: list[int] = []
    for clip_path in sorted(clips_dir.glob("clip_*.mp4")):
        match = CLIP_FILENAME_PATTERN.search(clip_path.stem)
        if match:
            try:
                indices.append(int(match.group(1)))
            except ValueError:
                continue
    return indices

def build_clip_batches(clip_indices: list[int], requested_batches: int, max_per_batch: int = MAX_CLIPS_PER_BATCH) -> list[list[int]]:
    """Creates clip index batches honoring requested counts and per-batch limits."""
    if not clip_indices:
        return []

    unique_indices = sorted(dict.fromkeys(clip_indices))
    required_batches = math.ceil(len(unique_indices) / max_per_batch)
    requested_batches = max(1, requested_batches)
    actual_batches = max(requested_batches, required_batches)
    actual_batches = min(actual_batches, len(unique_indices))
    chunk_size = max(1, math.ceil(len(unique_indices) / actual_batches))

    batches: list[list[int]] = []
    for start in range(0, len(unique_indices), chunk_size):
        batches.append(unique_indices[start:start + chunk_size])
    return batches

def run_remotion_render(
    props_dir: Path,
    final_output_dir: Path,
    remotion_app_dir: Path,
    reuse_existing_bundle: bool = False,
    on_clip_rendered=None,
):
    """
    Finds all prop JSON files and renders a video for each one using Remotion CLI.
    This function replaces the logic from the old render_all.ps1 script.
    """
    print("--- Starting Batch Remotion Rendering ---")

    prop_files = sorted(list(props_dir.glob("clip_*.json")))
    if not prop_files:
        print("No prop files (clip_*.json) found to render. Skipping.")
        return

    final_output_dir.mkdir(exist_ok=True)

    # Bundle the Remotion project once so every clip can reuse the same serve URL.
    bundle_dir = remotion_app_dir / "build"
    needs_bundle = True
    if bundle_dir.exists():
        if reuse_existing_bundle:
            print(f"Reusing existing Remotion bundle at {bundle_dir}")
            needs_bundle = False
        else:
            print(f"Removing existing Remotion bundle at {bundle_dir}")
            shutil.rmtree(bundle_dir)

    if needs_bundle:
        bundle_cmd = [
            "npx",
            "remotion",
            "bundle",
            "src/index.tsx",
            "--public-dir",
            "public",
            "--overwrite",
        ]
        run_command(bundle_cmd, "Bundling Remotion project", cwd=remotion_app_dir, quiet=True)

    if not bundle_dir.exists():
        raise RuntimeError(f"Remotion bundle not found after bundling step: {bundle_dir}")

    serve_url = os.path.relpath(bundle_dir.resolve(), remotion_app_dir.resolve())

    for prop_file in prop_files:
        base_name = prop_file.stem
        # Ensure the final output path is absolute before making it relative
        absolute_output_file = final_output_dir.resolve() / f"{base_name}.mp4"

        print(f"\nProcessing {prop_file.name}...")

        # Remotion CLI works relative to the app directory, so we must provide relative paths
        relative_output_path = os.path.relpath(absolute_output_file, remotion_app_dir)
        relative_props_path = os.path.relpath(prop_file.resolve(), remotion_app_dir)

        cmd = [
            "npx",
            "remotion",
            "render",
            "--serve-url",
            serve_url,
            "VideoWithBands",
            relative_output_path,
            "--props",
            relative_props_path,
        ]

        try:
            run_command(cmd, f"Rendering {absolute_output_file.name}", cwd=remotion_app_dir, quiet=True)
            print(f"  -> Successfully rendered: {absolute_output_file}")
            if on_clip_rendered:
                on_clip_rendered(prop_file, absolute_output_file)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"\n[ERROR] Remotion rendering failed for {prop_file.name}.", file=sys.stderr)
            raise e

    print("\n--- Batch Remotion Rendering Complete ---")


def main():
    parser = argparse.ArgumentParser(
        description="Run the full kirinuki generation pipeline from a YouTube video ID.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # ... (rest of the argument parser setup is unchanged)
    parser.add_argument("video_id", help="The YouTube video ID.")
    parser.add_argument("--subs", action="store_true", help="Burn subtitles into the generated clips.")
    parser.add_argument("--soft-subs", action="store_true", help="Export subtitle files without burning them.")
    parser.add_argument("--subs-format", choices=["srt", "ass"], default="ass", help="Subtitle format to use when subtitles are generated.")
    parser.add_argument(
        "--concept-file", 
        default="configs/video_concept.md", 
        help="Path to the video concept file. Defaults to configs/video_concept.md"
    )
    parser.add_argument(
        "--reaction",
        action="store_true",
        help="Generate reaction timelines and assets for each clip before rendering.",
    )
    parser.add_argument(
        "--reaction-character",
        default="Kirinuki Friend",
        help="Character name passed to the Gemini reaction generator (used with --reaction).",
    )
    parser.add_argument(
        "--reaction-max",
        type=int,
        default=6,
        help="Maximum reactions per clip when --reaction is enabled.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume processing using cached state if available.",
    )
    args = parser.parse_args()
    if args.subs and args.soft_subs:
        parser.error("--subs and --soft-subs cannot be used together.")

    # --- 1. Path Definitions ---
    tmp_dir = Path("tmp")
    video_path = tmp_dir / "video.mp4"
    transcript_path = tmp_dir / "transcript.json"
    
    remotion_app_dir = Path("apps/remotion")
    remotion_public_dir = remotion_app_dir / "public"
    clips_dir = remotion_public_dir / "out_clips"
    props_dir = remotion_public_dir / "props"
    re_encoded_dir = remotion_public_dir / "re_encoded_clips" # Legacy, but cleaned up
    remotion_bundle_dir = remotion_app_dir / "build"

    # This is the new global temp dir for Remotion, outside the app folder
    remotion_temp_dir = Path("remotion_tmp")
    
    final_output_dir = Path("rendered")
    final_output_dir.mkdir(exist_ok=True) # Ensure it exists before rendering

    drive_parent_id = os.environ.get("GDRIVE_PARENT_FOLDER_ID")
    if not drive_parent_id:
        raise RuntimeError("GDRIVE_PARENT_FOLDER_ID environment variable is required for Drive state synchronization.")
    drive_service = get_drive_service()

    state, state_file_name, state_file_id = load_state_from_drive(drive_service, drive_parent_id, args.video_id)
    resuming = bool(state) and (args.resume or state.get("status") in {"in-progress", "failed"})

    if resuming:
        print(f"Resuming progress for video {args.video_id} using Drive-backed state.")
        if state.get("status") == "completed":
            print("State indicates this video has already completed processing. Cleaning up leftover state file and exiting.")
            if state_file_id:
                delete_file(drive_service, state_file_id)
            return
    else:
        if state and not args.resume:
            print("Warning: Remote state exists but --resume not provided. Starting fresh and overwriting previous state.")
        state = {
            "videoId": args.video_id,
            "status": "in-progress",
            "sourceTitle": os.environ.get("SOURCE_VIDEO_TITLE", ""),
            "durationSeconds": 0.0,
            "requestedBatches": 1,
            "clipBatches": [],
            "completedBatches": [],
            "clips": {},
            "stages": {
                "download": {"done": False},
                "transcribe": {"done": False},
                "clips": {"done": False},
            },
        }
        resuming = False

    def persist_state():
        nonlocal state_file_id
        state_file_id = save_state_to_drive(drive_service, drive_parent_id, state_file_name, state, state_file_id)
        state["driveStateFileId"] = state_file_id
    persist_state()

    stages = state.setdefault("stages", {})
    artifacts = state.setdefault("artifacts", {})
    for key in ("download", "transcribe", "clips"):
        stage_info = stages.setdefault(key, {})
        stage_info.setdefault("done", False)
    clips_stage = stages["clips"]
    clips_manifest_info = artifacts.get("clipsManifest")
    clips_manifest: dict | None = None

    completed_batches = set(state.get("completedBatches", []))
    state["completedBatches"] = sorted(completed_batches)
    state.setdefault("clipBatches", [])
    state.setdefault("requestedBatches", max(1, int(state.get("requestedBatches", 1) or 1)))
    state.setdefault("durationSeconds", float(state.get("durationSeconds", 0.0) or 0.0))
    state.setdefault("clips", {})
    state["status"] = "in-progress"
    if os.environ.get("SOURCE_VIDEO_TITLE"):
        state["sourceTitle"] = os.environ["SOURCE_VIDEO_TITLE"]
    persist_state()

    duration_seconds: float = float(state.get("durationSeconds", 0.0) or 0.0)
    requested_batches = int(state.get("requestedBatches", 1) or 1)

    # --- 2. Pre-run Cleanup --- 
    print("--- Starting pre-run cleanup --- ")
    paths_to_clean = [
        tmp_dir,
        clips_dir,
        props_dir,
        re_encoded_dir,
        remotion_temp_dir,
        final_output_dir,
        remotion_bundle_dir,
    ]
    for path in paths_to_clean:
        if path.exists():
            if path.is_dir():
                print(f"Removing old directory: {path}")
                shutil.rmtree(path)
            else:
                print(f"Removing old file: {path}")
                path.unlink()

    tmp_dir.mkdir()
    final_output_dir.mkdir()

    # Cleanup old state files from Google Drive (failed states older than 7 days)
    print("Cleaning up old state files from Google Drive...")
    cleaned_count = cleanup_old_state_files(drive_service, drive_parent_id, args.video_id)
    if cleaned_count > 0:
        print(f"  -> Removed {cleaned_count} old state file(s)")
    else:
        print("  -> No old state files to remove")

    print("--- Pre-run cleanup complete ---\n")

    # This try...finally block ensures cleanup happens even if the pipeline fails
    try:
        download_stage = stages.get("download", {})
        need_download = not download_stage.get("done") or not video_path.exists()
        if need_download:
            # --- 3. Download Video ---
            cmd_download = [sys.executable, "download_video.py", args.video_id, "--output", str(video_path)]
            run_command(cmd_download, "Downloading YouTube Video")
            if not video_path.exists() or video_path.stat().st_size == 0:
                raise RuntimeError(f"Video download failed; file not found or empty at {video_path}")
            download_stage["done"] = True
            duration_seconds = probe_video_duration(video_path)
            state["durationSeconds"] = duration_seconds
            requested_batches = determine_batch_count(duration_seconds)
            state["requestedBatches"] = requested_batches
            persist_state()
        else:
            print("Download stage already marked complete; reusing existing video if present.")
            if not video_path.exists():
                print("Local video missing; re-downloading to ensure availability.")
                cmd_download = [sys.executable, "download_video.py", args.video_id, "--output", str(video_path)]
                run_command(cmd_download, "Re-downloading YouTube Video")
                if not video_path.exists() or video_path.stat().st_size == 0:
                    raise RuntimeError(f"Video download failed; file not found or empty at {video_path}")
            duration_seconds = float(state.get("durationSeconds", 0.0) or 0.0)
            if duration_seconds <= 0:
                duration_seconds = probe_video_duration(video_path)
                state["durationSeconds"] = duration_seconds
                persist_state()

        if not video_path.exists():
            raise RuntimeError("Video file is required but missing even after download stage.")

        requested_batches = max(1, int(state.get("requestedBatches", 1) or 1))
        if duration_seconds <= 0:
            duration_seconds = probe_video_duration(video_path)
            state["durationSeconds"] = duration_seconds
            persist_state()
            duration_seconds = float(state.get("durationSeconds", 0.0) or 0.0)

        if duration_seconds > 0:
            duration_minutes = duration_seconds / 60.0
            print(f"Detected video duration: {duration_minutes:.1f} minutes ({duration_seconds:.0f} seconds).")
        else:
            print("Could not determine video duration; defaulting to a single processing batch.")
            requested_batches = max(1, requested_batches)
        print(f"Processing batches planned: {requested_batches} (limit {MAX_CLIPS_PER_BATCH} clips per batch).")
        state["durationSeconds"] = duration_seconds
        state["requestedBatches"] = max(1, requested_batches)
        persist_state()

        transcribe_stage = stages.get("transcribe", {})
        need_transcribe = not transcribe_stage.get("done") or not transcript_path.exists()
        transcript_failed = False
        if need_transcribe:
            # --- 4. Transcribe Video ---
            cmd_transcribe = [sys.executable, "transcribe_rapidapi.py", args.video_id, "--output", str(transcript_path)]
            try:
                run_command(cmd_transcribe, "Transcribing Video")
            except subprocess.CalledProcessError:
                transcript_failed = True
            if not transcript_path.exists():
                transcript_failed = True
            if transcript_failed:
                print("Transcript generation failed; marking video as failed.", file=sys.stderr)
                state["status"] = "failed"
                state["failureReason"] = "transcript"
                persist_state()
                return
            transcribe_stage["done"] = True
            persist_state()
        else:
            print("Transcription stage already completed; reusing existing transcript.")
            if not transcript_path.exists():
                print("Transcript missing locally; regenerating to ensure availability.")
                cmd_transcribe = [sys.executable, "transcribe_rapidapi.py", args.video_id, "--output", str(transcript_path)]
                try:
                    run_command(cmd_transcribe, "Re-transcribing Video")
                except subprocess.CalledProcessError:
                    transcript_failed = True
                if not transcript_path.exists():
                    transcript_failed = True
                if transcript_failed:
                    print("Transcript regeneration failed; marking video as failed.", file=sys.stderr)
                    state["status"] = "failed"
                    state["failureReason"] = "transcript"
                    persist_state()
                    return

        # --- 5. Generate Clips ---
        if clips_stage.get("done") and not clips_dir.exists():
            if clips_manifest_info:
                clips_manifest = load_clips_manifest_from_drive(drive_service, clips_manifest_info)
                if clips_manifest and restore_clips_from_manifest(clips_manifest, video_path, clips_dir):
                    print("Restored clips directory from Drive manifest.")
                else:
                    print("Clips stage marked done but assets missing; regenerating clips.")
                    clips_stage["done"] = False
                    artifacts.pop("clipsManifest", None)
                    clips_manifest_info = None
                    clips_manifest = None
                    persist_state()

        need_generate = not clips_stage.get("done") or not clips_dir.exists()
        if need_generate:
            cmd_generate = [
                sys.executable, "-m", "apps.cli.generate_clips",
                "--transcript", str(transcript_path),
                "--video", str(video_path),
                "--out", str(clips_dir), # This now serves as an intermediate directory
                "--concept-file", args.concept_file
            ]
            if args.subs: cmd_generate.append("--subs")
            if args.soft_subs: cmd_generate.append("--soft-subs")
            if args.subs or args.soft_subs: cmd_generate.extend(["--subs-format", args.subs_format])
            if requested_batches > 1:
                max_clips_total = requested_batches * MAX_CLIPS_PER_BATCH
                cmd_generate.extend(["--max-clips", str(max_clips_total)])
            run_command(cmd_generate, "Generating Clips with AI")
            if not clips_dir.exists():
                raise RuntimeError(f"Expected clips directory missing: {clips_dir}")
            clips_stage["done"] = True
            persist_state()
        else:
            print("Clip generation already completed; reusing existing clips directory.")
            if not clips_dir.exists():
                print("Clip directory missing; regenerating clips to continue.")
                clips_stage["done"] = False
                persist_state()
                cmd_generate = [
                    sys.executable, "-m", "apps.cli.generate_clips",
                    "--transcript", str(transcript_path),
                    "--video", str(video_path),
                    "--out", str(clips_dir),
                    "--concept-file", args.concept_file
                ]
                if args.subs: cmd_generate.append("--subs")
                if args.soft_subs: cmd_generate.append("--soft-subs")
                if args.subs or args.soft_subs: cmd_generate.extend(["--subs-format", args.subs_format])
                if requested_batches > 1:
                    max_clips_total = requested_batches * MAX_CLIPS_PER_BATCH
                    cmd_generate.extend(["--max-clips", str(max_clips_total)])
                run_command(cmd_generate, "Regenerating Clips with AI")
                if not clips_dir.exists():
                    raise RuntimeError(f"Expected clips directory missing after regeneration: {clips_dir}")
                clips_stage["done"] = True
                persist_state()

        if clips_stage.get("done") and clips_dir.exists():
            manifest = build_clips_manifest(clips_dir)
            if manifest:
                manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                file_id = upload_json_data(
                    drive_service,
                    drive_parent_id,
                    f"clips_manifest_{args.video_id}.json",
                    manifest_payload,
                    clips_manifest_info.get("fileId") if clips_manifest_info else None,
                )
                clips_manifest_info = {
                    "fileId": file_id,
                    "updatedAt": _utc_now_iso(),
                }
                artifacts["clipsManifest"] = clips_manifest_info
                clips_manifest = manifest
                persist_state()

        # --- 5.5 Generate Reaction Timelines (optional) ---
        if args.reaction:
            candidates_path = clips_dir / "clip_candidates.json"
            if not candidates_path.exists():
                raise RuntimeError("Requested --reaction but clip_candidates.json is missing.")

            cmd_reaction = [
                sys.executable, "-m", "apps.cli.generate_reactions",
                "--transcript", str(transcript_path),
                "--clip-candidates", str(candidates_path),
                "--output-dir", str(clips_dir),
                "--max-reactions", str(max(1, args.reaction_max)),
                "--character-name", args.reaction_character,
            ]
            run_command(cmd_reaction, "Generating reactions for all clips")

        clips_state: dict = state["clips"]

        clip_indices = collect_clip_indices(clips_dir)
        if not clip_indices:
            raise RuntimeError("No clips were generated; cannot proceed with rendering.")

        computed_batches = build_clip_batches(clip_indices, requested_batches, MAX_CLIPS_PER_BATCH)
        stored_batches = state.get("clipBatches") or []
        if stored_batches:
            clip_batches = [[int(c) for c in batch] for batch in stored_batches]
            if not clip_batches:
                clip_batches = computed_batches
        else:
            clip_batches = computed_batches
            state["clipBatches"] = clip_batches
        if not clip_batches:
            raise RuntimeError("Failed to determine clip batches; aborting rendering.")

        if clip_batches != stored_batches:
            state["clipBatches"] = clip_batches
        state["totalClips"] = len(clip_indices)
        persist_state()

        total_pending = 0
        for clip_index in clip_indices:
            clip_key = f"{clip_index:03d}"
            clip_info = clips_state.get(clip_key)
            if clip_info and clip_info.get("uploaded"):
                continue
            total_pending += 1

        completed_batches = {
            idx
            for idx, batch in enumerate(clip_batches, start=1)
            if all(clips_state.get(f"{clip:03d}", {}).get("uploaded") for clip in batch)
        }
        state["completedBatches"] = sorted(completed_batches)
        persist_state()

        print(f"Total clips ready for rendering: {len(clip_indices)}")
        if len(clip_batches) != requested_batches:
            print(f"Adjusted batch count to {len(clip_batches)} based on available clips.")
        print(f"Batches to process: {len(clip_batches)} (max {MAX_CLIPS_PER_BATCH} clips per batch)")
        if len(clip_batches) > 1:
            for idx, batch in enumerate(clip_batches, start=1):
                clip_labels = ", ".join(f"{clip:03d}" for clip in batch)
                print(f"  Batch {idx}: {len(batch)} clips -> {clip_labels}")
        else:
            print("Processing all clips in a single batch.")
        print(f"Pending clips to process in this run: {total_pending}")

        if total_pending == 0:
            print("All clips have already been rendered and uploaded. Nothing to do.")
            state["status"] = "completed"
            persist_state()
            return

        state["driveFolderId"] = drive_parent_id
        sanitized_title = sanitize_filename((state.get("sourceTitle") or args.video_id)[:20])
        persist_state()

        for batch_idx, batch in enumerate(clip_batches, start=1):
            pending_in_batch = [
                clip_index for clip_index in batch
                if not clips_state.get(f"{clip_index:03d}", {}).get("uploaded")
            ]
            if not pending_in_batch:
                print(f"\n=== Skipping batch {batch_idx}/{len(clip_batches)}; already completed. ===")
                continue

            pending_keys = {f"{clip:03d}" for clip in pending_in_batch}

            def handle_rendered_clip(prop_path: Path, rendered_path: Path):
                match = PROPS_FILENAME_PATTERN.fullmatch(prop_path.name)
                clip_key = match.group(1) if match else None
                if not clip_key or clip_key not in pending_keys:
                    return
                upload_clip_and_props(
                    clip_key,
                    rendered_path,
                    prop_path,
                    sanitized_title,
                    drive_service,
                    drive_parent_id,
                    clips_state,
                    batch_idx,
                    persist_state,
                )
                pending_keys.discard(clip_key)

            batch_desc = f"batch {batch_idx}/{len(clip_batches)}"
            print(f"\n=== Starting {batch_desc} ({len(pending_in_batch)} clips) ===")

            if props_dir.exists():
                shutil.rmtree(props_dir)
            if re_encoded_dir.exists():
                shutil.rmtree(re_encoded_dir)

            cmd_prepare = [sys.executable, "-m", "apps.cli.render_clips", "--input-dir", str(clips_dir)]
            include_arg = ",".join(str(clip) for clip in pending_in_batch)
            cmd_prepare.extend(["--include-clips", include_arg])
            run_command(cmd_prepare, f"Preparing for Remotion Rendering ({batch_desc})", quiet=True)

            if not any(props_dir.glob("clip_*.json")):
                raise RuntimeError(f"Prop files (clip_*.json) were not generated for {batch_desc}. Cannot proceed with rendering.")

            reuse_bundle = batch_idx > 1
            run_remotion_render(
                props_dir,
                final_output_dir,
                remotion_app_dir,
                reuse_existing_bundle=reuse_bundle,
                on_clip_rendered=handle_rendered_clip,
            )

            # Update completion markers after batch uploads
            if all(clips_state.get(f"{clip:03d}", {}).get("uploaded") for clip in batch):
                completed_batches.add(batch_idx)
            state["completedBatches"] = sorted(completed_batches)
            persist_state()

        completed_batches = {
            idx
            for idx, batch in enumerate(clip_batches, start=1)
            if all(clips_state.get(f"{clip:03d}", {}).get("uploaded") for clip in batch)
        }
        state["completedBatches"] = sorted(completed_batches)
        total_uploaded = sum(1 for data in clips_state.values() if data.get("uploaded"))
        state["uploadedClips"] = total_uploaded
        persist_state()

        if len(completed_batches) == len(clip_batches):
            state["status"] = "completed"
            manifest_info = artifacts.pop("clipsManifest", None)
            manifest_file_id = manifest_info.get("fileId") if manifest_info else None
            if manifest_file_id:
                delete_file(drive_service, manifest_file_id)
            state_file_id_to_delete = state_file_id
            state_file_id = None
            if state_file_id_to_delete:
                delete_file(drive_service, state_file_id_to_delete)

        print("\n[OK] All steps completed successfully!")
        print(f"Uploaded clips to Google Drive folder: {drive_parent_id}\n")

    except RateLimitError as e:
        # Rate limit errors (429) should NOT persist failure state to Drive
        # This allows the video to be retried later without being marked as permanently failed
        print("\n[RATE LIMIT] The pipeline hit a rate limit (429 error).", file=sys.stderr)
        print(f"  - {e}", file=sys.stderr)
        print("\nThis video will NOT be marked as failed. Please retry after the rate limit resets.", file=sys.stderr)
        print("Intermediate files are kept in their respective directories for debugging.", file=sys.stderr)
        # Do NOT persist state - leave it as "in-progress" so it can be retried
        sys.exit(1)
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        print("\n[ERROR] The pipeline did not finish successfully.", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(f"  - Step failed: '{' '.join(e.cmd)}'", file=sys.stderr)
        else:
            print(f"  - Error: {e}", file=sys.stderr)
        print("\nIntermediate files are kept in their respective directories for debugging.", file=sys.stderr)
        state["status"] = "failed"
        if state_file_id:
            persist_state()
        sys.exit(1)
    finally:
        # --- 8. Final Cleanup ---
        # This block runs whether the try block succeeds or fails
        print("--- Starting final cleanup of intermediate files ---")
        # Clean up directories that are no longer needed after the final render
        paths_to_clean_finally = [clips_dir, re_encoded_dir, remotion_temp_dir, remotion_bundle_dir]
        for path in paths_to_clean_finally:
            if path.exists():
                print(f"Removing intermediate directory: {path}")
                shutil.rmtree(path, ignore_errors=True)
        # Note: We keep tmp_dir, props_dir, and final_output_dir for inspection after the run.
        print("--- Final cleanup complete ---\n")
        
        # Only persist state if we haven't completed (and thus deleted) the state file.
        if state.get("status") != "completed":
            persist_state()

if __name__ == "__main__":
    main()
