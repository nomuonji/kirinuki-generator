import argparse
import json
import pathlib
import re
import ffmpeg

def parse_hooks(hooks_path: pathlib.Path) -> (str, str):
    """Parses the _hooks.txt file to get upper and lower text."""
    upper_text = ""
    lower_text = ""
    try:
        content = hooks_path.read_text(encoding="utf-8")
        upper_match = re.search(r"UPPER:\n(.*?)\n\nLOWER:", content, re.DOTALL)
        if upper_match:
            upper_text = upper_match.group(1).strip()

        lower_match = re.search(r"LOWER:\n(.*?)$", content, re.DOTALL)
        if lower_match:
            lower_text = lower_match.group(1).strip()
    except Exception as e:
        print(f"  -> Warning: Could not parse hooks file {hooks_path}: {e}")
    return upper_text, lower_text

def get_duration_in_frames(video_path: pathlib.Path, fps: int = 30) -> int:
    """Gets the duration of a video in frames using ffmpeg."""
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        duration_sec = float(video_stream['duration'])
        return int(duration_sec * fps)
    except (ffmpeg.Error, StopIteration, KeyError, ValueError) as e:
        print(f"  -> ERROR: Could not get duration from {video_path}: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Prepare clips for Remotion rendering.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the original clips and hooks.")
    parser.add_argument("--skip-optimization", action="store_true", help="Skip the ffmpeg re-encoding step.")
    args = parser.parse_args()

    project_root = pathlib.Path(__file__).parent.parent.parent
    input_dir = project_root / args.input_dir

    remotion_public_dir = project_root / "apps" / "remotion" / "public"
    props_dir = remotion_public_dir / "props"
    re_encoded_dir = remotion_public_dir / "re_encoded_clips"
    props_dir.mkdir(exist_ok=True)
    re_encoded_dir.mkdir(exist_ok=True)

    clip_files = sorted(input_dir.glob("clip_*.mp4"))
    if not clip_files:
        print(f"No .mp4 clips found in {input_dir}. Exiting.")
        return

    video_dir_in_public = ""
    source_video_dir = None

    if args.skip_optimization:
        print("--- Skipping video optimization ---")
        source_video_dir = input_dir
        try:
            video_dir_in_public = input_dir.relative_to(remotion_public_dir).as_posix()
        except ValueError:
            print(f"  -> ERROR: Input directory must be inside {remotion_public_dir} when skipping.")
            return
    else:
        print("--- Optimizing all video clips for Remotion ---")
        source_video_dir = re_encoded_dir
        video_dir_in_public = re_encoded_dir.name
        for clip_path in clip_files:
            re_encoded_path = re_encoded_dir / clip_path.name
            print(f"  -> Optimizing: {clip_path.name}")
            try:
                ffmpeg.input(str(clip_path)).output(str(re_encoded_path), vcodec='libx264', preset='ultrafast', g=30, movflags='+faststart').overwrite_output().run(capture_stdout=True, capture_stderr=True)
            except ffmpeg.Error as e:
                print(f"  -> ERROR: Failed to re-encode {clip_path.name}. STDERR: {e.stderr.decode('utf-8')}")
                return
        print("--- Optimization Complete ---")

    print("\n--- Generating props files with duration ---")
    for clip_path in clip_files:
        match = re.search(r"clip_(\d{3})", clip_path.name)
        if not match: continue

        video_for_props = source_video_dir / clip_path.name
        duration_frames = get_duration_in_frames(video_for_props)
        if duration_frames == 0:
            print(f"  -> Skipping props generation for {clip_path.name} due to duration error.")
            continue

        hooks_path = clip_path.with_name(f"clip_{match.group(1)}_hooks.txt")
        if not hooks_path.exists():
            print(f"  -> Skipping: Hooks file not found for {clip_path.name}")
            continue

        upper_text, lower_text = parse_hooks(hooks_path)
        video_filename_prop = (pathlib.Path(video_dir_in_public) / clip_path.name).as_posix()
        
        props_dict = {
            "videoFileName": video_filename_prop,
            "topText": upper_text,
            "bottomText": lower_text,
            "durationInFrames": duration_frames
        }
        
        props_json_path = props_dir / f"{clip_path.stem}.json"
        with open(props_json_path, 'w', encoding='utf-8') as f:
            json.dump(props_dict, f, ensure_ascii=False, indent=2)
        print(f"  -> Created: {props_json_path} (Duration: {duration_frames} frames)")

    print("\n--- Preparation complete. ---")
    print("Next, run the rendering script: cd apps/remotion && .\render_all.ps1")

if __name__ == "__main__":
    main()