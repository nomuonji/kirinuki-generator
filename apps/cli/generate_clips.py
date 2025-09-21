import argparse, os, json, pathlib, subprocess, sys
from typing import List
from dotenv import load_dotenv
from packages.shared.io_utils import load_transcript
from packages.segmentation_gemini.client import (
    propose_clips_from_transcript,
    generate_hooks_bulk,
    HookText,
    ClipCandidate,
)
from packages.cutter_ffmpeg.cutter import cut_many, ClipSpec
from packages.subtitles.builder import clip_events_from_transcript, write_srt, write_ass

# Encoding-safe sentence-ending punctuation (Japanese + English)
SENTENCE_ENDS = (
    '.', '!', '?',           # ASCII
    '\u3002', '\uff01', '\uff1f',  # 。 ！ ？
    '\u2026',               # … (ellipsis)
    '\u266a',               # ♪
    '\u300d', '\u300f',    # 」 』
    '\uff09',               # ）
)

def refine_clip_end_time(p: ClipCandidate, items: List[dict], max_sec: float) -> float:
    """
    Refines the clip's end time based on the user's request:
    The end point is the start of the next segment, to include the full gap.
    """
    proposed_end = p.end
    final_segment_idx = -1

    # 1. Find the *last* segment that Gemini proposed as the end point.
    for idx, seg in enumerate(items):
        if abs(seg['end'] - proposed_end) < 1e-3:
            final_segment_idx = idx
    
    if final_segment_idx == -1:
        return proposed_end

    if final_segment_idx + 1 >= len(items):
        return items[final_segment_idx]['end']

    # 2. As per user request, the new end point is the start of the next segment,
    #    but with a small margin to avoid cutting off the last word.
    end_point = items[final_segment_idx + 1]['start']
    margin = 0.15  # 150ms margin
    new_end = max(items[final_segment_idx]['end'], end_point - margin)

    # 3. Ensure this new end point doesn't make the clip exceed max_sec.
    if new_end - p.start > max_sec:
        return items[final_segment_idx]['end']
    
    return new_end

def main():
    ap = argparse.ArgumentParser(description="Transcript -> Gemini -> edit points -> FFmpeg cutter (+ optional subtitles)")
    ap.add_argument("--transcript", required=True, help="path to .json/.jsonl transcript with {start,end,text}")
    ap.add_argument("--video", required=True, help="source video file")
    ap.add_argument("--out", required=True, help="output directory for clips")
    ap.add_argument("--platform", default="shorts", help="shorts|talk|educ (affects min/max)")
    ap.add_argument("--min-sec", type=float, default=20.0)
    ap.add_argument("--max-sec", type=float, default=90.0)
    ap.add_argument("--min-gap", type=float, default=30.0)
    ap.add_argument("--subs", action="store_true", help="generate per-clip subtitles (soft file)")
    ap.add_argument("--burn", action="store_true", help="burn-in subtitles into video (implies --subs)")
    ap.add_argument("--subs-format", choices=["srt","ass"], default="srt", help="subtitle format")
    ap.add_argument("--render", action="store_true", help="Render clips with Remotion after cutting.")
    ap.add_argument("--dry-run", action="store_true", help="only output JSON proposals")
    args = ap.parse_args()

    load_dotenv()
    items = load_transcript(args.transcript)

    if isinstance(items, dict) and 'segments' in items:
        items = items['segments']
    
    processed_items = []
    for item in items:
        try:
            start = float(item['start'])
            if 'end' in item:
                end = float(item['end'])
            elif 'dur' in item:
                end = start + float(item['dur'])
            elif 'duration' in item:
                end = start + float(item['duration'])
            else:
                continue
            text = item.get('text', '')
            if end <= start:
                continue
            processed_items.append({'start': start, 'end': end, 'text': text})
        except (KeyError, ValueError) as e:
            print(f"Skipping invalid item in transcript: {item}. Error: {e}")
            continue
    items = processed_items

    if not items:
        print("No valid transcript items found. Exiting.")
        return

    props = propose_clips_from_transcript(items, preset=args.platform,
                                          min_gap=args.min_gap, min_sec=args.min_sec, max_sec=args.max_sec)

    print("\n--- Verifying Gemini's Raw Proposals and Refining End Times ---")
    for i, p in enumerate(props, start=1):
        clip_transcript_items = [item for item in items if item['start'] >= p.start and item['end'] <= p.end]
        clip_transcript = "\n".join([f"  [{item['start']:.2f}-{item['end']:.2f}] {item['text']}" for item in clip_transcript_items])
        print(f"\n--- Proposal #{i}: {p.title} ---")
        print(f"  Reason: {p.reason}")
        print(f"  Transcript:\n{clip_transcript}")
        
        original_end = p.end
        refined_end = refine_clip_end_time(p, items, args.max_sec)
        p.end = refined_end

        print(f"  Timestamps: Start={p.start:.2f}, Raw End={original_end:.2f} -> Refined End={p.end:.2f}")
        print("------------------------------------------------------------------------")

    project_root = pathlib.Path(__file__).parent.parent.parent
    public_dir = project_root / "public"
    public_dir.mkdir(parents=True, exist_ok=True) # Ensure public dir exists
    outdir = public_dir / "out_clips"
    outdir.mkdir(parents=True, exist_ok=True) # Ensure out_clips dir exists

    json_path = outdir / "clip_candidates.json"
    json_path.write_text(json.dumps([p.model_dump() for p in props], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved proposals -> {json_path}")

    if args.dry_run:
        return

    bulk_inputs = []
    per_clip_transcript: dict[int, str] = {}
    for i, p in enumerate(props, start=1):
        clip_transcript_items = [item for item in items if item['start'] >= p.start and item['end'] <= p.end]
        clip_transcript = "\n".join([item['text'] for item in clip_transcript_items])
        per_clip_transcript[i] = clip_transcript
        bulk_inputs.append({"index": i, "transcript": clip_transcript})

    hooks_map: dict[int, HookText] = {}
    if any(per_clip_transcript.values()):
        print(f"Generating hook texts in bulk for {len(bulk_inputs)} clips...")
        hooks_map = generate_hooks_bulk(bulk_inputs)

    clip_specs = []
    for i, p in enumerate(props, start=1):
        print(f"\nProcessing clip {i}/{len(props)}: {p.title}")

        details_path = outdir / f"clip_{{i:03d}}_details.txt"
        details_content = f"Title: {p.title}\nReason: {p.reason}\nConfidence: {p.confidence:.2f}"
        details_path.write_text(details_content, encoding="utf-8")
        print(f"  -> Saved details to {details_path}")

        hooks = hooks_map.get(i, HookText(upper="", lower=""))
        hooks_path = outdir / f"clip_{{i:03d}}_hooks.txt"
        hooks_content = f"UPPER:\n{hooks.upper}\n\nLOWER:\n{hooks.lower}"
        hooks_path.write_text(hooks_content, encoding="utf-8")
        print(f"  -> Saved hooks to {hooks_path}")

        subs_path = None
        if args.subs or args.burn:
            events = clip_events_from_transcript(items, start=p.start, end=p.end)
            if args.subs_format == "srt":
                subs_path = str((outdir / f"clip_{{i:03d}}.srt").resolve())
                write_srt(events, pathlib.Path(subs_path))
            else:
                subs_path = str((outdir / f"clip_{{i:03d}}.ass").resolve())
                write_ass(events, pathlib.Path(subs_path))

        clip_specs.append(ClipSpec(
            start=p.start, end=p.end, index=i, title=p.title,
            subs_path=subs_path, burn=args.burn
        ))

    cut_many(args.video, clip_specs, args.out)
    print(f"done. {len(clip_specs)} clips saved in {args.out}")

    if args.render:
        print("\n--- Auto-starting Remotion rendering process ---")
        render_cmd = [
            sys.executable,
            "-m", "apps.cli.render_clips",
            "--input-dir", str(outdir) # Pass the correct outdir
        ]
        print(f"Running command: {" ".join(render_cmd)}")
        subprocess.run(render_cmd, check=True)

if __name__ == "__main__":
    main()