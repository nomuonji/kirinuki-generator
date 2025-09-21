import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path

def run_command(command, description, cwd=None):
    """Runs a command and prints its description."""
    print(f"--- {description} ---")
    cmd_str = ' '.join(map(str, command))
    print(f"Executing: {cmd_str}")
    try:
        subprocess.run(command, check=True, cwd=cwd, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR during '{description}':")
        print(e.stdout)
        print(e.stderr)
        raise e
    print(f"--- Finished: {description} ---\n")

def main():
    parser = argparse.ArgumentParser(
        description="Run the full kirinuki generation pipeline from a YouTube video ID.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("video_id", help="The YouTube video ID.")
    parser.add_argument(
        "--concept-file", 
        default="configs/video_concept.md", 
        help="Path to the video concept file. Defaults to configs/video_concept.md"
    )
    args = parser.parse_args()

    # --- 1. Path Definitions ---
    tmp_dir = Path("tmp")
    video_path = tmp_dir / "video.mp4"
    transcript_path = tmp_dir / "transcript.json"
    
    remotion_public_dir = Path("apps/remotion/public")
    clips_dir = remotion_public_dir / "out_clips"
    props_dir = remotion_public_dir / "props"
    re_encoded_dir = remotion_public_dir / "re_encoded_clips"
    
    final_output_dir = Path("rendered")

    # --- 2. Pre-run Cleanup --- 
    print("--- Starting pre-run cleanup --- ")
    # Clean up directories from previous runs
    paths_to_clean = [tmp_dir, clips_dir, props_dir, re_encoded_dir]
    for path in paths_to_clean:
        if path.exists():
            print(f"Removing old directory: {path}")
            shutil.rmtree(path)
    print("--- Pre-run cleanup complete ---\n")
    
    # Recreate tmp_dir for the current run
    tmp_dir.mkdir()

    try:
        # --- 3. Download Video ---
        cmd_download = [sys.executable, "download_video.py", args.video_id, "--output", str(video_path)]
        run_command(cmd_download, "Downloading YouTube Video")

        # --- 4. Transcribe Video ---
        cmd_transcribe = [sys.executable, "transcribe_rapidapi.py", args.video_id]
        run_command(cmd_transcribe, "Transcribing Video")

        # --- 5. Generate Clips ---
        cmd_generate = [
            sys.executable, "-m", "apps.cli.generate_clips",
            "--transcript", str(transcript_path),
            "--video", str(video_path),
            "--out", str(clips_dir),
            "--concept-file", args.concept_file
        ]
        run_command(cmd_generate, "Generating Clips with AI")
        
        # --- 6. Prepare for Rendering ---
        cmd_prepare = [
            sys.executable, "-m", "apps.cli.render_clips",
            "--input-dir", str(clips_dir)
        ]
        run_command(cmd_prepare, "Preparing for Remotion Rendering")

        # --- Cleanup 1: Original clips ---
        print(f"--- Cleaning up original clips directory: {clips_dir} ---")
        shutil.rmtree(clips_dir)
        print("--- Cleanup complete ---\n")

        # --- 7. Final Rendering ---
        cmd_render = ["powershell", "-File", ".\\render_all.ps1"]
        run_command(cmd_render, "Starting Final Remotion Rendering", cwd="apps/remotion")

        # --- Cleanup 2: Remotion work files ---
        print("--- Cleaning up Remotion work files ---")
        if props_dir.exists():
            print(f"Removing directory: {props_dir}")
            shutil.rmtree(props_dir)
        if re_encoded_dir.exists():
            print(f"Removing directory: {re_encoded_dir}")
            shutil.rmtree(re_encoded_dir)
        print("--- Cleanup complete ---\n")

        print("\n[32m[1m✨✨✨ All steps completed successfully! ✨✨✨[0m")
        print(f"Your final videos are ready in: \033[4m{final_output_dir.resolve()}\033[0m\n")

    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        print(f"\n\033[91m\033[1m❌ An error occurred. ❌\033[0m")
        if isinstance(e, subprocess.CalledProcessError):
             print(f"  - Step failed: '{e.cmd}'")
        else:
            print(f"  - Error: {e}")
        print("\nIntermediate files are kept in their respective directories for debugging.")
        sys.exit(1)

if __name__ == "__main__":
    main()
