import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path

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

def run_remotion_render(props_dir: Path, final_output_dir: Path, remotion_app_dir: Path):
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
    if bundle_dir.exists():
        print(f"Removing existing Remotion bundle at {bundle_dir}")
        shutil.rmtree(bundle_dir)

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

    # --- 2. Pre-run Cleanup --- 
    print("--- Starting pre-run cleanup --- ")
    # Extended cleanup to include the new top-level remotion_tmp
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

    # Re-create necessary directories
    tmp_dir.mkdir()
    final_output_dir.mkdir()

    print("--- Pre-run cleanup complete ---\n")

    # This try...finally block ensures cleanup happens even if the pipeline fails
    try:
        # --- 3. Download Video ---
        cmd_download = [sys.executable, "download_video.py", args.video_id, "--output", str(video_path)]
        run_command(cmd_download, "Downloading YouTube Video")
        if not video_path.exists() or video_path.stat().st_size == 0:
            raise RuntimeError(f"Video download failed; file not found or empty at {video_path}")

        # --- 4. Transcribe Video ---
        cmd_transcribe = [sys.executable, "transcribe_rapidapi.py", args.video_id, "--output", str(transcript_path)]
        run_command(cmd_transcribe, "Transcribing Video")

        # --- 5. Generate Clips ---
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
        run_command(cmd_generate, "Generating Clips with AI")
        
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

        # --- 6. Prepare for Rendering (Generates props) ---
        cmd_prepare = [sys.executable, "-m", "apps.cli.render_clips", "--input-dir", str(clips_dir)]
        run_command(cmd_prepare, "Preparing for Remotion Rendering")

        # Verify that prop files were created before proceeding
        if not any(props_dir.glob("clip_*.json")):
            raise RuntimeError("Prop files (clip_*.json) were not generated. Cannot proceed with rendering.")

        # --- 7. Final Rendering (Replaces PowerShell script) ---
        run_remotion_render(props_dir, final_output_dir, remotion_app_dir)

        print("\n[OK] All steps completed successfully!")
        print(f"Your final videos are ready in: {final_output_dir.resolve()}\n")

    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        print("\n[ERROR] The pipeline did not finish successfully.", file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(f"  - Step failed: '{' '.join(e.cmd)}'", file=sys.stderr)
        else:
            print(f"  - Error: {e}", file=sys.stderr)
        print("\nIntermediate files are kept in their respective directories for debugging.", file=sys.stderr)
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

if __name__ == "__main__":
    main()
