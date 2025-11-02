import argparse, os, json, pathlib, subprocess, sys
from typing import List
from dotenv import load_dotenv
from packages.shared.io_utils import load_transcript
from packages.segmentation_gemini.client import (
    propose_clips_from_transcript,
    generate_hooks_bulk,
    HookText,
    ClipCandidate,
    polish_subtitles,
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
    ap.add_argument("--min-sec", type=float, default=30.0)
    ap.add_argument("--max-sec", type=float, default=120.0)
    ap.add_argument("--min-gap", type=float, default=30.0)
    ap.add_argument("--max-clips", type=int, default=30,
                    help="Maximum number of clips to keep from Gemini proposals (default: 30).")
    ap.add_argument("--subs", action="store_true", help="Burn subtitles into the output clips (hard subtitles).")
    ap.add_argument("--soft-subs", action="store_true", help="Generate external subtitle files without burning them.")
    ap.add_argument("--subs-format", choices=["srt","ass"], default="srt", help="Subtitle format to generate when subtitles are enabled")
    ap.add_argument("--render", action="store_true", help="Render clips with Remotion after cutting.")
    ap.add_argument("--dry-run", action="store_true", help="only output JSON proposals")
    ap.add_argument("--concept", type=str, default="", help="Concept of the video to guide Gemini's generation")
    ap.add_argument("--concept-file", type=str, default=None, help="Path to a file containing the concept of the video")
    ap.add_argument("--batch-size", type=int, default=30, help="Batch size for bulk processing hooks")
    args = ap.parse_args()
    if args.subs and args.soft_subs:
        ap.error("--subs and --soft-subs cannot be used together.")
    burn_subs = args.subs
    soft_subs = args.soft_subs
    needs_subs = burn_subs or soft_subs

    load_dotenv()

    concept = args.concept
    if args.concept_file:
        try:
            concept_path = pathlib.Path(args.concept_file)
            if concept_path.is_file():
                concept = concept_path.read_text(encoding="utf-8")
                print(f"Loaded concept from: {args.concept_file}")
            else:
                print(f"Warning: Concept file not found at {args.concept_file}")
        except Exception as e:
            print(f"Warning: Failed to read concept file: {e}")

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
                                          min_gap=args.min_gap, min_sec=args.min_sec, max_sec=args.max_sec, concept=concept)
    if args.max_clips > 0 and len(props) > args.max_clips:
        print(f"\nLimiting clip proposals from {len(props)} to top {args.max_clips} entries.")
        props = props[: args.max_clips]

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

    # --out引数で指定されたディレクトリをPathオブジェクトとして扱う
    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

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
        hooks_map = generate_hooks_bulk(bulk_inputs, concept=concept, batch_size=args.batch_size)

    clip_specs = []
    for i, p in enumerate(props, start=1):
        print(f"\nProcessing clip {i}/{len(props)}: {p.title}")

        hooks = hooks_map.get(i, HookText(upper="", lower=""))
        hooks_payload = {
            "upper_plain": getattr(hooks, 'upper', ''),
            "lower_plain": getattr(hooks, 'lower', ''),
            "upper_decorated": getattr(hooks, 'upper_decorated', '') or getattr(hooks, 'upper', ''),
            "lower_decorated": getattr(hooks, 'lower_decorated', '') or getattr(hooks, 'lower', ''),
            "hashtags": list(getattr(hooks, 'hashtags', []) or []),
        }

        details_path = outdir / f"clip_{i:03d}_details.txt"
        details_content = f"Title: {p.title}\nPunchline: {p.punchline}\nReason: {p.reason}\nConfidence: {p.confidence:.2f}"
        if hooks_payload['hashtags']:
            details_content += f"\nHashtags: {' '.join(hooks_payload['hashtags'])}"
        details_path.write_text(details_content, encoding="utf-8")
        print(f"  -> Saved details to {details_path}")

        hooks_path = outdir / f"clip_{i:03d}_hooks.txt"
        hooks_path.write_text(json.dumps(hooks_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> Saved hooks to {hooks_path}")
        subs_path = None
        if needs_subs:
            events = clip_events_from_transcript(items, start=p.start, end=p.end)
            try:
                cleaned_lines = polish_subtitles([ev['text'] for ev in events], concept=concept)
                if len(cleaned_lines) == len(events):
                    for ev, cleaned in zip(events, cleaned_lines):
                        ev['text'] = cleaned
            except Exception as exc:
                print(f"  -> Warning: Subtitle polishing skipped ({exc})")
            
            # Instead of writing SRT/ASS, write a JSON file for Remotion
            subs_json_path = outdir / f"clip_{i:03d}_subtitles.json"
            with open(subs_json_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
            print(f"  -> Saved Remotion subtitles to {subs_json_path}")

        # The spec no longer needs subtitle paths for burning
        clip_specs.append(ClipSpec(
            start=p.start, end=p.end, index=i, title=p.title,
            subs_path=None, burn=False
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
        print(f"Running command: {' '.join(render_cmd)}")
        subprocess.run(render_cmd, check=True)

if __name__ == "__main__":
    main()
