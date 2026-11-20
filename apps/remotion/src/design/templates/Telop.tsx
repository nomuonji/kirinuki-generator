import React from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, spring, useCurrentFrame} from "remotion";
import {
  DesignProps,
  FONT,
  RichLines,
  SAFE,
  allText,
  charUnits,
  ellipsis,
  entryOpacity,
  fitRich,
  jpWrap,
  parseRich,
  plainText,
  strokeText,
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/**
 * 定番の切り抜きShorts: black canvas, a two-tone outlined headline on top, the clip enlarged in
 * the middle, the spoken line burned in over the bottom edge of the clip and a second outlined
 * line under it. Modelled on the layout most outlier clip Shorts in YouTube Studio's research
 * tab share (2026-11), rather than on a designed "theme".
 *
 * `frame: "zoom"` crops the clip to 4:3 so faces are bigger; `"wide"` keeps the full frame.
 */
type Ink = {fill: string; stroke: string; glow?: string};
type Palette = {lineA: Ink; lineB: Ink; hl: Ink; punch: Ink; reaction: Ink; frame: "zoom" | "wide"};

const PALETTES = [
  {
    lineA: {fill: "#FFFFFF", stroke: "#FF2E7E", glow: "#FF2E7E"},
    lineB: {fill: "#FF2E7E", stroke: "#FFFFFF"},
    hl: {fill: "#FFE94A", stroke: "#1A1A1A"},
    punch: {fill: "#FF2E7E", stroke: "#FFFFFF"},
    reaction: {fill: "#FF4F9A", stroke: "#FFFFFF"},
    frame: "zoom",
  },
  {
    lineA: {fill: "#FFFFFF", stroke: "#111111"},
    lineB: {fill: "#E8132B", stroke: "#FFFFFF"},
    hl: {fill: "#FFE600", stroke: "#111111"},
    punch: {fill: "#E8132B", stroke: "#FFFFFF"},
    reaction: {fill: "#FFE600", stroke: "#111111"},
    frame: "wide",
  },
  {
    lineA: {fill: "#B45CFF", stroke: "#FFFFFF"},
    lineB: {fill: "#FF5FA8", stroke: "#FFFFFF"},
    hl: {fill: "#FF5FA8", stroke: "#FFFFFF"},
    punch: {fill: "#FFFFFF", stroke: "#B45CFF", glow: "#B45CFF"},
    reaction: {fill: "#FF5FA8", stroke: "#FFFFFF"},
    frame: "zoom",
  },
];
const TYPED_PALETTES: Palette[] = PALETTES as Palette[];

export const TELOP_VARIANTS = PALETTES.length;

const ROUNDED = `'M PLUS Rounded 1c', ${FONT.sans}`;
const SIDE = 44;

const inkStyle = (ink: Ink, size: number, ratio = 0.16): React.CSSProperties => ({
  color: ink.fill,
  ...strokeText(Math.max(5, Math.round(size * ratio)), ink.stroke),
  // A thin dark rim outside the stroke keeps white-stroked text readable on bright footage.
  filter: ink.glow
    ? `drop-shadow(0 0 ${Math.round(size * 0.12)}px ${ink.glow}) drop-shadow(0 0 2px ${ink.glow})`
    : "drop-shadow(0 3px 0 rgba(0,0,0,0.55))",
});

export const Telop: React.FC<DesignProps> = (p) => {
  useFontsReady(["900 90px 'M PLUS Rounded 1c'", "900 56px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = TYPED_PALETTES[p.variant % TYPED_PALETTES.length];

  // Clip box: full canvas width, enlarged to 4:3 in "zoom" mode.
  const clipAspect = p.aspect; // Do not crop participants to 4:3.
  const clipH = Math.min(900, Math.round(1080 / clipAspect));
  const clipTop = 560;
  const clipBottom = clipTop + clipH;

  const titleTop = 178;
  const titleH = clipTop - titleTop - 26;
  const titleW = 1080 - 2 * SIDE;
  const titleLines = parseRich(p.title).length || 1;
  const titleSize = fitRich(p.title, titleW, titleH, {max: titleLines > 2 ? 96 : 112, min: 52, lineHeight: 1.18, widthFactor: 1.08});
  // The headline hugs the top of the clip (as in the reference Shorts); the kicker sits just above it.
  const titleRows = plainText(p.title)
    .split("\n")
    .reduce((n, line) => n + Math.max(1, Math.ceil((charUnits(line) * titleSize * 1.08) / titleW)), 0);
  const titleBlockTop = Math.max(titleTop, clipTop - 26 - titleRows * titleSize * 1.18);
  const titleIn = spring({frame, fps: p.fps, config: {damping: 12, stiffness: 180}});

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - SAFE.left;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 190, {max: 68, min: 40, lineHeight: 1.25}) : 68;
  const subPop = sub.entry ? interpolate(sub.local, [0, 4], [0.9, 1], {extrapolateRight: "clamp"}) : 1;

  const punchTop = clipBottom + 26;
  const punchH = SAFE.bottom - punchTop;
  const punchW = SAFE.right - SAFE.left;
  const punchSize = fitRich(p.punchline, punchW, punchH, {max: 76, min: 40, lineHeight: 1.2, widthFactor: 1.08});

  const reaction = useReaction(p.reactions);
  const reactionIn = reaction.entry ? spring({frame: reaction.local, fps: p.fps, config: {damping: 10, stiffness: 240}}) : 0;
  const reactionSize = reaction.entry ? Math.max(38, Math.min(60, Math.floor(560 / Math.max(1, [...reaction.entry.text].length)))) : 0;
  const tilt = p.seed % 2 ? -6 : 6;

  return (
    <AbsoluteFill style={{background: "#000", overflow: "hidden"}}>
      {/* Very dark, scene-derived backdrop fills otherwise dead 9:16 space.
          The existing two-tone hook, uncut scene, captions and payoff remain unchanged. */}
      <AbsoluteFill style={{overflow:"hidden"}}>
        <OffthreadVideo muted src={p.videoSrc}
          style={{width:"100%",height:"100%",objectFit:"cover",
                  filter:"blur(55px) brightness(0.23)",transform:"scale(1.12)"}} />
      </AbsoluteFill>
      {/* Source as a quiet lead-in line, like the "もうさ.." / "今までは…" kicker above clip titles */}
      {/* Two-tone outlined headline: lines alternate between the two inks */}
      <div
        style={{
          position: "absolute",
          top: titleTop,
          left: SIDE,
          width: titleW,
          height: titleH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          textAlign: "center",
          fontFamily: ROUNDED,
          fontWeight: 900,
          fontSize: titleSize,
          lineHeight: 1.18,
          transform: `scale(${interpolate(titleIn, [0, 1], [0.94, 1])})`,
          transformOrigin: "center bottom",
          ...jpWrap,
        }}
      >
        {parseRich(p.title).map((_, li) => {
          const lineInk = li % 2 === 0 ? c.lineA : c.lineB;
          // Re-render one line at a time so each line can carry its own ink.
          const lineRich = p.title.split("\n").filter((l) => l.trim())[li] ?? "";
          return (
            <div key={li} style={inkStyle(lineInk, titleSize)}>
              <RichLines rich={lineRich} hlStyle={() => ({...inkStyle(c.hl, titleSize), display: "inline"})} />
            </div>
          );
        })}
      </div>

      {/* The clip, edge to edge */}
      <div style={{position: "absolute", top: clipTop, left: 0, width: 1080, height: clipH, overflow: "hidden", background: "#000"}}>
        <OffthreadVideo
          src={p.videoSrc}
          style={{width: "100%", height: "100%", objectFit: "contain"}}
        />
      </div>

      {/* Reaction cut-in on the clip */}
      {reaction.entry ? (
        <div
          style={{
            position: "absolute",
            top: clipTop + 34,
            left: SAFE.left + 6,
            maxWidth: 620,
            fontFamily: ROUNDED,
            fontWeight: 900,
            fontSize: reactionSize,
            lineHeight: 1.15,
            transform: `rotate(${tilt}deg) scale(${reactionIn})`,
            transformOrigin: "left center",
            opacity: entryOpacity(reaction.local, reaction.length, 6),
            ...inkStyle(c.reaction, reactionSize, 0.18),
            ...jpWrap,
          }}
        >
          {reaction.entry.text}
        </div>
      ) : null}

      {/* Spoken line burned in over the bottom edge of the clip */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            bottom: 1920 - clipBottom + 35,
            left: SAFE.left,
            width: subW,
            textAlign: "center",
            fontFamily: ROUNDED,
            fontWeight: 900,
            fontSize: subSize,
            lineHeight: 1.25,
            color: "#fff",
            ...strokeText(Math.round(subSize * 0.22), "#111"),
            filter: "drop-shadow(0 4px 0 rgba(0,0,0,0.6))",
            transform: `scale(${subPop})`,
            transformOrigin: "center bottom",
            opacity: entryOpacity(sub.local, sub.length, 3),
            ...jpWrap,
          }}
        >
          {sub.entry.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}

      {/* Second outlined line under the clip */}
      <div
        style={{
          position: "absolute",
          top: punchTop,
          left: SAFE.left,
          width: punchW,
          height: punchH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-start",
          textAlign: "center",
          fontFamily: ROUNDED,
          fontWeight: 900,
          fontSize: punchSize,
          lineHeight: 1.2,
          ...inkStyle(c.punch, punchSize),
          ...jpWrap,
        }}
      >
        <RichLines rich={p.punchline} hlStyle={() => ({...inkStyle(c.hl, punchSize), display: "inline"})} />
      </div>
    </AbsoluteFill>
  );
};
