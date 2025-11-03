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

MAX_CLIPS_PER_BATCH = 15
CLIP_FILENAME_PATTERN = re.compile(r"clip_(\d+)\.mp4")
STATE_FILENAME = "state.json"

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    _ensure_dir(dst.parent)
    shutil.copy2(src, dst)

def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    _ensure_dir(dst.parent)
    shutil.copytree(src, dst)

def load_state(cache_dir: Path, video_id: str) -> dict:
    state_path = cache_dir / video_id / STATE_FILENAME
    if not state_path.exists():
        return {}
    try:
        with state_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Failed to load state file {state_path}: {exc}", file=sys.stderr)
        return {}

def save_state(cache_dir: Path, video_id: str, state: dict) -> None:
    state_dir = cache_dir / video_id
    _ensure_dir(state_dir)
    state["lastUpdated"] = _utc_now_iso()
    state_path = state_dir / STATE_FILENAME
    with state_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)

def run_command(command, description, cwd=None):
    """Runs a command, streaming its output in real-time."""
    print(f"--- {description} ---")
    cmd_str = ' '.join(map(str, command))
    print(f"Executing: {cmd_str}")

    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Redirect stderr to stdout
            text=True,
            encoding='utf-8',
            errors='ignore',
            cwd=cwd
        )

        # Read and print output line by line
        for line in iter(process.stdout.readline, ''):
            print(line, end='')

        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)

        print(f"\n--- Finished: {description} ---\n")

    except subprocess.CalledProcessError as e:
        print(f"\nERROR during '{description}': Command returned non-zero exit status {e.returncode}.", file=sys.stderr)
        # Re-raise the exception to be caught by the main pipeline's error handler
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
        match = CLIP_FILENAME_PATTERN.fullmatch(clip_path.name)
        if match:
            indices.append(int(match.group(1)))
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

def run_remotion_render(props_dir: Path, final_output_dir: Path, remotion_app_dir: Path, reuse_existing_bundle: bool = False):
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
        run_command(bundle_cmd, "Bundling Remotion project", cwd=remotion_app_dir)

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
            run_command(cmd, f"Rendering {absolute_output_file.name}", cwd=remotion_app_dir)
            print(f"  -> Successfully rendered: {absolute_output_file}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"\n[ERROR] Remotion rendering failed for {prop_file.name}.", file=sys.stderr)
            # The detailed error is already printed by run_command, so we just re-raise
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
        "--cache-dir",
        default="cache",
        help="Directory used to store intermediate state for resuming long jobs (default: cache).",
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

    cache_root = Path(args.cache_dir)
    cache_video_dir = cache_root / args.video_id
    existing_state = load_state(cache_root, args.video_id)
    resuming = bool(existing_state) and (args.resume or existing_state.get("status") in {"in-progress", "failed"})

    if resuming:
        state = existing_state
        print(f"Resuming cached progress for video {args.video_id} (cache: {cache_video_dir})")
        if state.get("status") == "completed":
            print("Cached state indicates this video is already completed. Exiting.")
            return
    else:
        if existing_state and not args.resume:
            print("Warning: Cached state exists but --resume not provided. Starting fresh and overwriting previous cache.")
        state = {
            "videoId": args.video_id,
            "status": "in-progress",
            "sourceTitle": os.environ.get("SOURCE_VIDEO_TITLE", ""),
            "durationSeconds": 0.0,
            "requestedBatches": 1,
            "clipBatches": [],
            "completedBatches": [],
            "stages": {
                "download": {"done": False},
                "transcribe": {"done": False},
                "clips": {"done": False},
            },
        }
        resuming = False

    stages = state.setdefault("stages", {})
    for key in ("download", "transcribe", "clips"):
        stage_info = stages.setdefault(key, {})
        stage_info.setdefault("done", False)

    completed_batches = set(state.get("completedBatches", []))
    state["completedBatches"] = sorted(completed_batches)
    state.setdefault("clipBatches", [])
    state.setdefault("requestedBatches", max(1, int(state.get("requestedBatches", 1) or 1)))
    state.setdefault("durationSeconds", float(state.get("durationSeconds", 0.0) or 0.0))
    state["status"] = "in-progress"
    if os.environ.get("SOURCE_VIDEO_TITLE"):
        state["sourceTitle"] = os.environ["SOURCE_VIDEO_TITLE"]
    save_state(cache_root, args.video_id, state)

    cache_inputs_dir = cache_video_dir / "inputs"
    cache_clips_dir = cache_video_dir / "clips"
    cache_batches_dir = cache_video_dir / "batches"
    cache_rendered_dir = cache_video_dir / "rendered"

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

    if resuming:
        if stages.get("download", {}).get("done"):
            cached_video = cache_inputs_dir / "video.mp4"
            if cached_video.exists():
                _copy_file(cached_video, video_path)
                print(f"Restored cached video to {video_path}")
        if stages.get("transcribe", {}).get("done"):
            cached_transcript = cache_inputs_dir / "transcript.json"
            if cached_transcript.exists():
                _copy_file(cached_transcript, transcript_path)
                print(f"Restored cached transcript to {transcript_path}")
        if stages.get("clips", {}).get("done") and cache_clips_dir.exists():
            _copy_tree(cache_clips_dir, clips_dir)
            print(f"Restored cached clips to {clips_dir}")
        if cache_rendered_dir.exists():
            _copy_tree(cache_rendered_dir, final_output_dir)
            print(f"Restored cached rendered outputs to {final_output_dir}")

    print("--- Pre-run cleanup complete ---\n")

    # This try...finally block ensures cleanup happens even if the pipeline fails
    try:
        download_stage = stages.get("download", {})
        if not download_stage.get("done"):
            # --- 3. Download Video ---
            cmd_download = [sys.executable, "download_video.py", args.video_id, "--output", str(video_path)]
            run_command(cmd_download, "Downloading YouTube Video")
            if not video_path.exists() or video_path.stat().st_size == 0:
                raise RuntimeError(f"Video download failed; file not found or empty at {video_path}")
            _copy_file(video_path, cache_inputs_dir / video_path.name)
            download_stage["done"] = True
            duration_seconds = probe_video_duration(video_path)
            state["durationSeconds"] = duration_seconds
            requested_batches = determine_batch_count(duration_seconds)
            state["requestedBatches"] = requested_batches
            save_state(cache_root, args.video_id, state)
        else:
            print("Download stage already completed; using cached video.")
            cached_video = cache_inputs_dir / video_path.name
            if not video_path.exists() and cached_video.exists():
                _copy_file(cached_video, video_path)
                print(f"Restored cached video to {video_path}")
            duration_seconds = float(state.get("durationSeconds", 0.0) or 0.0)
            if duration_seconds <= 0 and video_path.exists():
                duration_seconds = probe_video_duration(video_path)
                state["durationSeconds"] = duration_seconds
            requested_batches = int(state.get("requestedBatches", 1) or 1)

        if duration_seconds > 0:
            duration_minutes = duration_seconds / 60.0
            print(f"Detected video duration: {duration_minutes:.1f} minutes ({duration_seconds:.0f} seconds).")
        else:
            print("Could not determine video duration; defaulting to a single processing batch.")
            requested_batches = max(1, requested_batches)
        print(f"Processing batches planned: {requested_batches} (limit {MAX_CLIPS_PER_BATCH} clips per batch).")
        state["durationSeconds"] = duration_seconds
        state["requestedBatches"] = max(1, requested_batches)
        save_state(cache_root, args.video_id, state)

        transcribe_stage = stages.get("transcribe", {})
        if not transcribe_stage.get("done"):
            # --- 4. Transcribe Video ---
            cmd_transcribe = [sys.executable, "transcribe_rapidapi.py", args.video_id, "--output", str(transcript_path)]
            run_command(cmd_transcribe, "Transcribing Video")
            if not transcript_path.exists():
                raise RuntimeError(f"Transcript not found at {transcript_path}")
            _copy_file(transcript_path, cache_inputs_dir / transcript_path.name)
            transcribe_stage["done"] = True
            save_state(cache_root, args.video_id, state)
        else:
            print("Transcription stage already completed; using cached transcript.")
            cached_transcript = cache_inputs_dir / transcript_path.name
            if not transcript_path.exists() and cached_transcript.exists():
                _copy_file(cached_transcript, transcript_path)
                print(f"Restored cached transcript to {transcript_path}")

        # --- 5. Generate Clips ---
        clips_stage = stages.get("clips", {})
        if not clips_stage.get("done"):
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
            _copy_tree(clips_dir, cache_clips_dir)
            clips_stage["done"] = True
            save_state(cache_root, args.video_id, state)
        else:
            print("Clip generation already completed; using cached clips.")
            if not clips_dir.exists() and cache_clips_dir.exists():
                _copy_tree(cache_clips_dir, clips_dir)
                print(f"Restored cached clips to {clips_dir}")
        
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
        save_state(cache_root, args.video_id, state)

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

        completed_batches = set(state.get("completedBatches", []))
        state["completedBatches"] = sorted(completed_batches)
        save_state(cache_root, args.video_id, state)

        for batch_idx, batch in enumerate(clip_batches, start=1):
            if batch_idx in completed_batches:
                print(f"\n=== Skipping batch {batch_idx}/{len(clip_batches)}; already completed. ===")
                continue
            batch_desc = f"batch {batch_idx}/{len(clip_batches)}"
            print(f"\n=== Starting {batch_desc} ({len(batch)} clips) ===")

            if props_dir.exists():
                shutil.rmtree(props_dir)
            if re_encoded_dir.exists():
                shutil.rmtree(re_encoded_dir)

            cmd_prepare = [sys.executable, "-m", "apps.cli.render_clips", "--input-dir", str(clips_dir)]
            if len(clip_batches) > 1:
                include_arg = ",".join(str(clip) for clip in batch)
                cmd_prepare.extend(["--include-clips", include_arg])
            run_command(cmd_prepare, f"Preparing for Remotion Rendering ({batch_desc})")

            if not any(props_dir.glob("clip_*.json")):
                raise RuntimeError(f"Prop files (clip_*.json) were not generated for {batch_desc}. Cannot proceed with rendering.")

            reuse_bundle = batch_idx > 1
            run_remotion_render(
                props_dir,
                final_output_dir,
                remotion_app_dir,
                reuse_existing_bundle=reuse_bundle,
            )

            batch_cache_dir = cache_batches_dir / f"batch_{batch_idx:02d}"
            batch_props_dir = batch_cache_dir / "props"
            batch_rendered_dir = batch_cache_dir / "rendered"
            _copy_tree(props_dir, batch_props_dir)
            if batch_rendered_dir.exists():
                shutil.rmtree(batch_rendered_dir)
            _ensure_dir(batch_rendered_dir)
            for clip_index in batch:
                rendered_file = final_output_dir / f"clip_{clip_index:03d}.mp4"
                if rendered_file.exists():
                    _copy_file(rendered_file, batch_rendered_dir / rendered_file.name)
            _copy_tree(final_output_dir, cache_rendered_dir)

            completed_batches.add(batch_idx)
            state["completedBatches"] = sorted(completed_batches)
            save_state(cache_root, args.video_id, state)

        if len(completed_batches) == len(clip_batches):
            state["status"] = "completed"
            save_state(cache_root, args.video_id, state)

        print("\n[OK] All steps completed successfully!")
        print(f"Your final videos are ready in: {final_output_dir.resolve()}\n")

    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        print("\n[ERROR] The pipeline did not finish successfully.", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(f"  - Step failed: '{' '.join(e.cmd)}'", file=sys.stderr)
        else:
            print(f"  - Error: {e}", file=sys.stderr)
        print("\nIntermediate files are kept in their respective directories for debugging.", file=sys.stderr)
        state["status"] = "failed"
        save_state(cache_root, args.video_id, state)
        sys.exit(1)
    finally:
        # --- 8. Final Cleanup ---
        # This block runs whether the try block succeeds or fails
        print("--- Starting final cleanup of intermediate files ---")
        if final_output_dir.exists():
            _copy_tree(final_output_dir, cache_rendered_dir)
        # Clean up directories that are no longer needed after the final render
        paths_to_clean_finally = [clips_dir, re_encoded_dir, remotion_temp_dir, remotion_bundle_dir]
        for path in paths_to_clean_finally:
            if path.exists():
                print(f"Removing intermediate directory: {path}")
                shutil.rmtree(path, ignore_errors=True)
        # Note: We keep tmp_dir, props_dir, and final_output_dir for inspection after the run.
        print("--- Final cleanup complete ---\n")
        save_state(cache_root, args.video_id, state)

if __name__ == "__main__":
    main()
