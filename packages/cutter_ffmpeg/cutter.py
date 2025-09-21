import os, subprocess, pathlib, time
from typing import List, Optional
from dataclasses import dataclass
import concurrent.futures

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_FFMPEG_TASKS", "4"))

@dataclass
class ClipSpec:
    start: float
    end: float
    index: int
    title: str = ""
    subs_path: Optional[str] = None  # SRT/ASS
    burn: bool = False

def _run_ffmpeg(cmd: List[str], spec: ClipSpec):
    """Helper to run a single ffmpeg command and handle its output."""
    try:
        # Using Popen to better control stdout/stderr
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            # Print detailed error message if ffmpeg fails
            print(f"--- FFMPEG FAILED for clip {spec.index} ---")
            print(f"CMD: {' '.join(cmd)}")
            print("STDERR:")
            print(stderr)
            return False
        return True
    except FileNotFoundError:
        print(f"Error: '{FFMPEG_BIN}' not found. Please ensure ffmpeg is installed and in your PATH.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while running ffmpeg for clip {spec.index}: {e}")
        return False

def _prepare_command(video_path: pathlib.Path, spec: ClipSpec, out_file: pathlib.Path) -> List[str]:
    """Prepares the ffmpeg command list for a given ClipSpec."""
    duration = max(0.0, spec.end - spec.start)

    # Part 1: Input options (fast seek)
    input_opts = [
        "-ss", f"{spec.start:.3f}",
        "-i", str(video_path),
        "-t", f"{duration:.3f}",
    ]

    # Part 2: Filter options (subtitles only, no fades)
    vf_filters = []  # No video filters by default
    if spec.burn and spec.subs_path:
        subs_path = pathlib.Path(spec.subs_path).as_posix()
        if subs_path.lower().endswith(".srt"):
            escaped_path = subs_path.replace('\\', '/').replace(':', '\\:')
            vf_filters.append(f"subtitles='{escaped_path}'")
        else:  # ASS
            vf_filters.append(f"ass='{subs_path}'")

    filter_opts = []
    if vf_filters:
        filter_opts.extend(["-vf", ",".join(vf_filters)])

    # Part 3: Output options (re-encoding everything)
    output_opts = [
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y",
        str(out_file)
    ]

    # Combine all parts
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error"] + input_opts + filter_opts + output_opts
    return cmd

def cut_many(video: str, clips: List[ClipSpec], out_dir: str) -> None:
    video_path = pathlib.Path(video)
    outp = pathlib.Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)

    print(f"\nCutting {len(clips)} clips using up to {MAX_CONCURRENT_TASKS} parallel tasks...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS) as executor:
        future_to_spec = {}
        for spec in clips:
            base = f"clip_{spec.index:03d}_{int(spec.start)}-{int(spec.end)}"
            out_file = outp / f"{base}.mp4"
            
            cmd = _prepare_command(video_path, spec, out_file)
            
            future = executor.submit(_run_ffmpeg, cmd, spec)
            future_to_spec[future] = spec

        successful_cuts = 0
        for i, future in enumerate(concurrent.futures.as_completed(future_to_spec)):
            spec = future_to_spec[future]
            try:
                success = future.result()
                if success:
                    successful_cuts += 1
                    print(f"({i+1}/{len(clips)}) Successfully cut clip {spec.index:03d} -> {out_file.name}")
                else:
                    print(f"({i+1}/{len(clips)}) Failed to cut clip {spec.index:03d}")
            except Exception as exc:
                print(f"({i+1}/{len(clips)}) Clip {spec.index:03d} generated an exception: {exc}")

    print(f"\nDone. {successful_cuts}/{len(clips)} clips were cut successfully and saved in '{out_dir}'.")