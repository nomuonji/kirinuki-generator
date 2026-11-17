import React from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, spring, useCurrentFrame} from "remotion";
import {
  DesignProps,
  FONT,
  RichLines,
  SAFE,
  allText,
  ellipsis,
  entryOpacity,
  fitRich,
  jpWrap,
  parseRich,
  strokeText,
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/**
 * 論客・時事の切り抜きShorts (ひろゆき lane). Modelled on the outliers in YouTube Studio's
 * research tab for a Hiroyuki clip channel (2026-11): a square heavy-gothic headline phrased as
 * a claim or question on a solid band or in big brackets, the speaker cropped tight so the face
 * fills the middle, the spoken line burned in white with a black outline, and a solid plate under
 * the clip carrying the punchline. A small 出典 credit sits on the clip.
 *
 * Unlike `telop` (rounded, glowing, built for 恋リア clips) everything here is square, flat and
 * high-contrast: red / yellow / white on black, like a news or debate caption.
 */
type Palette = {
  head: "band" | "bracket" | "plain";
  headBg: string;
  lineA: string;
  lineB: string;
  hl: string;
  plateBg: string;
  plateInk: string;
  plateHl: string;
  plateBorder: string;
};

const PALETTES = [
  {
    head: "band",
    headBg: "#E60012",
    lineA: "#FFFFFF",
    lineB: "#FFE600",
    hl: "#FFE600",
    plateBg: "#E60012",
    plateInk: "#FFE600",
    plateHl: "#FFFFFF",
    plateBorder: "#E60012",
  },
  {
    head: "bracket",
    headBg: "#000000",
    lineA: "#FFFFFF",
    lineB: "#FF2B2B",
    hl: "#FF2B2B",
    plateBg: "#000000",
    plateInk: "#FFFFFF",
    plateHl: "#FFE600",
    plateBorder: "#FFFFFF",
  },
  {
    head: "plain",
    headBg: "#000000",
    lineA: "#FFFFFF",
    lineB: "#FFE600",
    hl: "#FFE600",
    plateBg: "#FFE600",
    plateInk: "#111111",
    plateHl: "#E60012",
    plateBorder: "#FFE600",
  },
];
const TYPED_PALETTES: Palette[] = PALETTES as Palette[];

export const RONPA_VARIANTS = PALETTES.length;

const SANS = FONT.sans;
const HEAD_TOP = SAFE.top + 20;
const CLIP_TOP = 560;
const CLIP_ASPECT = 5 / 4; // tight crop: the speaker's face fills the middle of the frame

export const Ronpa: React.FC<DesignProps> = (p) => {
  useFontsReady(["900 90px 'Noto Sans JP'", "800 40px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = TYPED_PALETTES[p.variant % TYPED_PALETTES.length];

  const clipAspect = Math.min(p.aspect, CLIP_ASPECT);
  const clipH = Math.round(1080 / clipAspect);
  const clipBottom = CLIP_TOP + clipH;

  const headPadX = c.head === "bracket" ? 92 : 50;
  const headW = 1080 - 2 * headPadX;
  const headH = CLIP_TOP - HEAD_TOP - 50;
  const lines = parseRich(p.title).length || 1;
  const headSize = fitRich(p.title, headW, headH, {max: lines > 2 ? 100 : 118, min: 52, lineHeight: 1.16, widthFactor: 1.06});
  const headIn = spring({frame, fps: p.fps, config: {damping: 14, stiffness: 200}});
  const titleLines = p.title.split("\n").filter((l) => l.trim());

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - SAFE.left;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 200, {max: 66, min: 40, lineHeight: 1.24}) : 66;

  const plateTop = clipBottom + 18;
  const plateH = Math.max(110, SAFE.bottom - plateTop);
  const plateW = SAFE.right - SAFE.left;
  const plateSize = fitRich(p.punchline, plateW - 56, plateH - 40, {max: 70, min: 38, lineHeight: 1.2, widthFactor: 1.06});

  const reaction = useReaction(p.reactions);
  const reactionIn = reaction.entry ? interpolate(reaction.local, [0, 4], [0, 1], {extrapolateRight: "clamp"}) : 0;

  const headStroke = (color: string) => ({
    color,
    ...strokeText(Math.max(4, Math.round(headSize * (c.head === "band" ? 0.07 : 0.1))), "#000"),
    textShadow: c.head === "band" ? "0 5px 0 rgba(0,0,0,0.35)" : "none",
  });

  return (
    <AbsoluteFill style={{background: "#000", overflow: "hidden"}}>
      {/* Headline zone */}
      <div style={{position: "absolute", top: 0, left: 0, width: 1080, height: CLIP_TOP, background: c.headBg}} />
      {c.head === "bracket" ? (
        <>
          <div style={{position: "absolute", top: HEAD_TOP, left: 40, width: 46, height: headH + 20, borderLeft: "12px solid #fff", borderTop: "12px solid #fff", borderBottom: "12px solid #fff"}} />
          <div style={{position: "absolute", top: HEAD_TOP, right: 40, width: 46, height: headH + 20, borderRight: "12px solid #fff", borderTop: "12px solid #fff", borderBottom: "12px solid #fff"}} />
        </>
      ) : null}
      <div
        style={{
          position: "absolute",
          top: HEAD_TOP + 10,
          left: headPadX,
          width: headW,
          height: headH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          textAlign: "center",
          fontFamily: SANS,
          fontWeight: 900,
          fontSize: headSize,
          lineHeight: 1.16,
          letterSpacing: "-0.02em",
          transform: `scale(${interpolate(headIn, [0, 1], [0.95, 1])})`,
          ...jpWrap,
        }}
      >
        {titleLines.map((line, li) => (
          <div key={li} style={headStroke(li % 2 === 0 ? c.lineA : c.lineB)}>
            <RichLines rich={line} hlStyle={() => ({color: c.hl})} />
          </div>
        ))}
      </div>

      {/* Speaker, cropped tight */}
      <div style={{position: "absolute", top: CLIP_TOP, left: 0, width: 1080, height: clipH, overflow: "hidden", background: "#000"}}>
        <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "cover"}} />
      </div>

      {/* 出典 credit */}
      {p.sourceTitle ? (
        <div
          style={{
            position: "absolute",
            top: CLIP_TOP + 14,
            right: 24,
            maxWidth: 640,
            padding: "4px 12px",
            background: "rgba(0,0,0,0.55)",
            color: "rgba(255,255,255,0.88)",
            fontFamily: SANS,
            fontWeight: 800,
            fontSize: 24,
            ...ellipsis,
          }}
        >
          出典：{p.sourceTitle}
        </div>
      ) : null}

      {/* Reaction as a flat caption tag */}
      {reaction.entry ? (
        <div
          style={{
            position: "absolute",
            top: CLIP_TOP + 70,
            left: SAFE.left - 20,
            maxWidth: 640,
            padding: "8px 20px 10px",
            background: "#FFE600",
            color: "#111",
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: 44,
            lineHeight: 1.2,
            transform: `translateX(${interpolate(reactionIn, [0, 1], [-40, 0])}px)`,
            opacity: entryOpacity(reaction.local, reaction.length, 5) * reactionIn,
            boxShadow: "6px 6px 0 rgba(0,0,0,0.6)",
            ...jpWrap,
          }}
        >
          {reaction.entry.text}
        </div>
      ) : null}

      {/* Spoken line over the lower part of the clip */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            bottom: 1920 - clipBottom + 26,
            left: SAFE.left,
            width: subW,
            textAlign: "center",
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: subSize,
            lineHeight: 1.24,
            color: "#fff",
            ...strokeText(Math.round(subSize * 0.2), "#000"),
            opacity: entryOpacity(sub.local, sub.length, 3),
            ...jpWrap,
          }}
        >
          {sub.entry.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}

      {/* Punchline plate */}
      <div
        style={{
          position: "absolute",
          top: plateTop,
          left: SAFE.left,
          width: plateW,
          height: plateH,
          boxSizing: "border-box",
          background: c.plateBg,
          border: `6px solid ${c.plateBorder}`,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "12px 28px",
          textAlign: "center",
          fontFamily: SANS,
          fontWeight: 900,
          fontSize: plateSize,
          lineHeight: 1.2,
          color: c.plateInk,
          ...jpWrap,
        }}
      >
        <RichLines rich={p.punchline} hlStyle={() => ({color: c.plateHl})} />
      </div>
    </AbsoluteFill>
  );
};
