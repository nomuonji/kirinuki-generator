import React, {useEffect, useState} from "react";
import {continueRender, delayRender, interpolate, useCurrentFrame} from "remotion";

export type SubtitleEntry = {startFrame: number; endFrame: number; text: string};
export type ReactionEntry = {startFrame: number; durationInFrames: number; text: string; emotion?: string};

/** Everything a template needs; templates never read raw Remotion props. */
export type DesignProps = {
  videoSrc: string;
  title: string; // rich text: **word** marks emphasis, \n is a line break
  punchline: string; // rich text
  sourceTitle: string;
  aspect: number;
  durationInFrames: number;
  fps: number;
  subtitles: SubtitleEntry[];
  reactions: ReactionEntry[];
  variant: number;
  seed: number;
};

/**
 * Shorts-safe vertical zones on the 1080x1920 canvas. The YouTube Shorts player draws its
 * title/channel/buttons over roughly the bottom 300px and a ~130px column on the right side
 * of the lower half, so readable text stays inside SAFE and decorative elements alone may
 * extend past it.
 */
export const SAFE = {
  top: 110,
  bottom: 1615,
  left: 60,
  right: 1080 - 140,
};

export type RichSegment = {text: string; hl: boolean};

export const normalizeRich = (value: string): string =>
  (value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/[\u2028\u2029]/g, "\n")
    .trim();

export const parseRich = (value: string): RichSegment[][] =>
  normalizeRich(value)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) =>
      line
        .split(/(\*\*[^*]+\*\*)/g)
        .filter(Boolean)
        .map((chunk) =>
          /^\*\*[^*]+\*\*$/.test(chunk) ? {text: chunk.slice(2, -2), hl: true} : {text: chunk.replace(/\*\*/g, ""), hl: false},
        ),
    );

export const plainText = (value: string): string => parseRich(value).map((l) => l.map((s) => s.text).join("")).join("\n");

/** Approximate rendered width in em: CJK is full width, Latin/digits about half. */
export const charUnits = (s: string): number => {
  let units = 0;
  for (const ch of s) {
    const code = ch.codePointAt(0) ?? 0;
    if (/\s/.test(ch)) units += 0.3;
    else if (code < 0x2e80 || (code >= 0xff61 && code <= 0xff9f)) units += 0.58;
    else units += 1;
  }
  return units;
};

/** Largest font size (px) whose estimated wrapped block fits the box. */
export const fitFontSize = (
  lines: string[],
  boxW: number,
  boxH: number,
  {max, min, lineHeight, widthFactor = 1.12}: {max: number; min: number; lineHeight: number; widthFactor?: number},
): number => {
  const safeLines = lines.length ? lines : [""];
  // Prefer keeping each authored line on one row (no orphaned 「る」は) as long as that
  // doesn't shrink the text below ~62% of the maximum.
  const longest = Math.max(...safeLines.map(charUnits), 1);
  const unbroken = Math.min(max, Math.floor(boxW / (longest * widthFactor)), Math.floor(boxH / (safeLines.length * lineHeight)));
  if (unbroken >= Math.max(min, max * 0.62)) return unbroken;
  for (let size = max; size > min; size -= 2) {
    let rows = 0;
    for (const line of safeLines) {
      rows += Math.max(1, Math.ceil((charUnits(line) * size * widthFactor) / boxW));
    }
    if (rows * size * lineHeight <= boxH) return size;
  }
  return min;
};

export const fitRich = (
  rich: string,
  boxW: number,
  boxH: number,
  opts: {max: number; min: number; lineHeight: number; widthFactor?: number},
) => fitFontSize(plainText(rich).split("\n"), boxW, boxH, opts);

export const useActive = <T extends {startFrame: number}>(entries: T[], end: (e: T) => number) => {
  const frame = useCurrentFrame();
  const entry = entries.find((e) => frame >= e.startFrame && frame < end(e));
  return {entry, local: entry ? frame - entry.startFrame : 0, length: entry ? end(entry) - entry.startFrame : 0};
};

export const useSubtitle = (subs: SubtitleEntry[]) => useActive(subs, (s) => s.endFrame);
export const useReaction = (items: ReactionEntry[]) => useActive(items, (r) => r.startFrame + r.durationInFrames);

/** 0..1 fade for an entry that is `local` frames in and `length` frames long. */
export const entryOpacity = (local: number, length: number, fade = 5) => {
  if (length <= fade * 2) return 1;
  return interpolate(local, [0, fade, length - fade, length], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

export const mulberry = (seed: number) => {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

export const hashString = (value: string): number => {
  let h = 2166136261;
  for (const ch of value) {
    h ^= ch.codePointAt(0) ?? 0;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

export const clock = (frames: number, fps: number) => {
  const total = Math.max(0, Math.floor(frames / fps));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

/**
 * Hold the frame until every face this template uses is loaded for the exact characters on
 * screen. Fontsource splits Japanese fonts into unicode-range subsets that the browser only
 * fetches on demand, so without this the first frames could render in a fallback face.
 */
export const useFontsReady = (fontSpecs: string[], text: string) => {
  const [handle] = useState(() => delayRender("Loading template fonts", {timeoutInMilliseconds: 60000}));
  useEffect(() => {
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        continueRender(handle);
      }
    };
    const sample = `${text}0123456789:/.>「」！？ー`;
    Promise.all(fontSpecs.map((spec) => document.fonts.load(spec, sample)))
      .then(() => document.fonts.ready)
      .then(finish, finish);
    const timer = setTimeout(finish, 30000);
    return () => clearTimeout(timer);
  }, [handle]);
};

export const allText = (p: DesignProps) =>
  [p.title, p.punchline, p.sourceTitle, ...p.subtitles.map((s) => s.text), ...p.reactions.map((r) => r.text)]
    .map(plainText)
    .join("");

export const RichLines: React.FC<{
  rich: string;
  hlStyle: (index: number) => React.CSSProperties;
  lineStyle?: React.CSSProperties;
  /** Reveal only the first N characters (typewriter); undefined shows everything. */
  visibleChars?: number;
  renderSegment?: (seg: RichSegment, key: string, index: number) => React.ReactNode;
}> = ({rich, hlStyle, lineStyle, visibleChars, renderSegment}) => {
  let budget = visibleChars ?? Number.POSITIVE_INFINITY;
  let hlIndex = 0;
  return (
    <>
      {parseRich(rich).map((line, li) => (
        <div key={`l${li}`} style={{display: "block", ...lineStyle}}>
          {line.map((seg, si) => {
            if (budget <= 0) return null;
            const chars = [...seg.text];
            const shown = chars.slice(0, Math.max(0, Math.floor(budget))).join("");
            budget -= chars.length;
            const piece = {text: shown, hl: seg.hl};
            const key = `s${li}-${si}`;
            if (renderSegment) return renderSegment(piece, key, seg.hl ? hlIndex++ : -1);
            if (seg.hl) {
              const style = hlStyle(hlIndex++);
              return (
                <span key={key} style={style}>
                  {shown}
                </span>
              );
            }
            return <span key={key}>{shown}</span>;
          })}
        </div>
      ))}
    </>
  );
};

export const totalChars = (rich: string) => [...plainText(rich).replace(/\n/g, "")].length;

export const strokeText = (width: number, color: string): React.CSSProperties => ({
  // @ts-ignore paint-order is valid CSS but missing from React's types
  paintOrder: "stroke fill",
  WebkitTextStroke: `${width}px ${color}`,
});

export const ellipsis: React.CSSProperties = {
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export const jpWrap: React.CSSProperties = {
  // Phrase-aware Japanese line breaking (needs lang="ja" on an ancestor): keeps 結婚 and
  // ひろゆき whole instead of breaking at any character.
  // @ts-ignore auto-phrase is newer than React's CSS types
  wordBreak: "auto-phrase",
  lineBreak: "strict",
  overflowWrap: "anywhere",
  // @ts-ignore text-wrap is supported by the Chromium Remotion ships
  textWrap: "balance",
};

export const FONT = {
  sans: "'Noto Sans JP', 'Noto Sans CJK JP', sans-serif",
  mincho: "'Shippori Mincho B1', 'Noto Serif CJK JP', serif",
  dela: "'Dela Gothic One', 'Noto Sans JP', sans-serif",
  dot: "'DotGothic16', 'Noto Sans JP', monospace",
  zen: "'Zen Kaku Gothic New', 'Noto Sans JP', sans-serif",
  hand: "'Yusei Magic', 'Noto Sans JP', sans-serif",
};
