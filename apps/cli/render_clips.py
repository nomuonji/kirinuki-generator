import argparse
import json
import pathlib
import re
import ffmpeg


FRAME_RATE = 30


def _normalize_plain_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_hashtags(raw) -> list[str]:
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple, set)):
        candidates = list(raw)
    else:
        candidates = []
    hashtags: list[str] = []
    for tag in candidates:
        if not tag:
            continue
        tag_str = str(tag).strip()
        if not tag_str:
            continue
        if not tag_str.startswith('#'):
            tag_str = '#' + tag_str.lstrip('#').strip()
        if tag_str and tag_str not in hashtags:
            hashtags.append(tag_str)
        if len(hashtags) >= 5:
            break
    return hashtags


def parse_hooks(hooks_path: pathlib.Path) -> dict[str, object]:
    """Parses the _hooks.txt file to get decorated and plain overlay text."""
    defaults = {
        'upper_plain': '',
        'lower_plain': '',
        'upper_decorated': '',
        'lower_decorated': '',
        'hashtags': [],
    }
    try:
        content = hooks_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"  -> Warning: Could not read hooks file {hooks_path}: {exc}")
        return defaults

    try:
        data = json.loads(content)
        upper_decorated = str(
            data.get('upper_decorated')
            or data.get('upperDecorated')
            or ''
        )
        lower_decorated = str(
            data.get('lower_decorated')
            or data.get('lowerDecorated')
            or ''
        )
        upper_plain = _normalize_plain_text(
            str(data.get('upper_plain') or data.get('upperPlain') or '')
        )
        lower_plain = _normalize_plain_text(
            str(data.get('lower_plain') or data.get('lowerPlain') or '')
        )
        if not upper_plain:
            upper_plain = _normalize_plain_text(upper_decorated)
        if not lower_plain:
            lower_plain = _normalize_plain_text(lower_decorated)
        hashtags = _normalize_hashtags(data.get('hashtags') or data.get('hashTags'))
        return {
            'upper_plain': upper_plain,
            'lower_plain': lower_plain,
            'upper_decorated': upper_decorated,
            'lower_decorated': lower_decorated,
            'hashtags': hashtags,
        }
    except json.JSONDecodeError:
        pass

    # Legacy plain-text format fallback
    upper_match = re.search(r"UPPER:\n(.*?)\n\nLOWER:", content, re.DOTALL)
    lower_match = re.search(r"LOWER:\n(.*?)$", content, re.DOTALL)
    upper_text = upper_match.group(1).strip() if upper_match else ''
    lower_text = lower_match.group(1).strip() if lower_match else ''
    upper_plain = _normalize_plain_text(upper_text)
    lower_plain = _normalize_plain_text(lower_text)
    return {
        'upper_plain': upper_plain,
        'lower_plain': lower_plain,
        'upper_decorated': upper_text,
        'lower_decorated': lower_text,
        'hashtags': [],
    }


def get_duration_in_frames(video_path: pathlib.Path, fps: int = FRAME_RATE) -> int:
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

    candidates_map: dict[str, tuple[float, float]] = {}
    clip_candidates_path = input_dir / 'clip_candidates.json'
    if clip_candidates_path.exists():
        try:
            candidates_payload = json.loads(clip_candidates_path.read_text(encoding='utf-8'))
            if isinstance(candidates_payload, list):
                for idx, clip_info in enumerate(candidates_payload, start=1):
                    try:
                        start_val = float(clip_info.get('start'))
                        end_val = float(clip_info.get('end'))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if end_val <= start_val:
                        continue
                    candidates_map[f'clip_{idx:03d}'] = (start_val, end_val)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  -> Warning: Could not parse {clip_candidates_path}: {exc}")

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

        clip_id = f"clip_{match.group(1)}"
        candidate_span = candidates_map.get(clip_id)
        candidate_duration_frames = None
        if candidate_span:
            candidate_duration_frames = max(1, round((candidate_span[1] - candidate_span[0]) * FRAME_RATE))
            if duration_frames < candidate_duration_frames:
                duration_frames = candidate_duration_frames

        if duration_frames == 0:
            if candidate_duration_frames:
                duration_frames = candidate_duration_frames
            else:
                print(f"  -> Skipping props generation for {clip_path.name} due to duration error.")
                continue

        hooks_path = clip_path.with_name(f"clip_{match.group(1)}_hooks.txt")
        if not hooks_path.exists():
            print(f"  -> Skipping: Hooks file not found for {clip_path.name}")
            continue

        hooks_data = parse_hooks(hooks_path)
        upper_plain = hooks_data['upper_plain']
        lower_plain = hooks_data['lower_plain']
        upper_decorated = hooks_data['upper_decorated'] or upper_plain
        lower_decorated = hooks_data['lower_decorated'] or lower_plain
        hashtags = hooks_data.get('hashtags', [])
        video_filename_prop = (pathlib.Path(video_dir_in_public) / clip_path.name).as_posix()

        reaction_timeline: list[dict[str, object]] = []
        reactions_path = clip_path.with_name(f"clip_{match.group(1)}_reactions.json")
        if reactions_path.exists():
            try:
                with reactions_path.open("r", encoding="utf-8") as reactions_file:
                    reactions_payload = json.load(reactions_file)
                raw_entries = reactions_payload.get("reactions")
                if isinstance(raw_entries, list):
                    for entry in raw_entries:
                        if not isinstance(entry, dict):
                            continue
                        try:
                            start_sec = float(
                                entry.get("startTimeSec")
                                or entry.get("start")
                                or entry.get("timeSec")
                                or 0
                            )
                            duration_sec = float(
                                entry.get("durationSec")
                                or entry.get("duration")
                                or entry.get("lenSec")
                                or entry.get("lengthSec")
                                or 0
                            )
                        except (TypeError, ValueError):
                            continue
                        text = str(entry.get("text") or "").strip()
                        if not text:
                            continue
                        start_frame = max(0, round(start_sec * FRAME_RATE))
                        reaction_duration_frames = max(1, round(duration_sec * FRAME_RATE))
                        reaction_entry: dict[str, object] = {
                            "startFrame": start_frame,
                            "durationInFrames": reaction_duration_frames,
                            "text": text,
                        }
                        emotion = entry.get("emotion") or entry.get("mood")
                        if isinstance(emotion, str) and emotion.strip():
                            reaction_entry["emotion"] = emotion.strip()
                        reaction_timeline.append(reaction_entry)
                else:
                    print(f"  -> Warning: Unexpected reactions format in {reactions_path}")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  -> Warning: Could not read reactions from {reactions_path}: {exc}")

        props_dict = {
            "videoFileName": video_filename_prop,
            "topText": upper_plain,
            "bottomText": lower_plain,
            "topRichText": upper_decorated,
            "bottomRichText": lower_decorated,
            "hashtags": hashtags,
            "durationInFrames": duration_frames,
            "reactionTimeline": reaction_timeline,
        }

        props_json_path = props_dir / f"{clip_path.stem}.json"
        with open(props_json_path, 'w', encoding='utf-8') as f:
            json.dump(props_dict, f, ensure_ascii=False, indent=2)

        print(f"  -> Created: {props_json_path} (Duration: {duration_frames} frames)")

    print("\n--- Preparation complete. ---")
    print("Next, run the rendering script: cd apps/remotion && .\render_all.ps1")

if __name__ == "__main__":
    main()
