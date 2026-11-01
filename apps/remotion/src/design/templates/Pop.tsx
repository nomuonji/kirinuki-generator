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
  strokeText,
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/** 雑誌表紙: flat vivid colour, heavy Dela Gothic headline, the clip as a tilted card with a hard shadow. */
const PALETTES = [
  {bg: "#FFE14A", hot: "#FF2D6F"},
  {bg: "#5BE3FF", hot: "#FF3B2F"},
  {bg: "#FF9BCB", hot: "#2B59FF"},
];

export const POP_VARIANTS = PALETTES.length;

const INK = "#111111";
const CARD_X = 54;
const CARD_W = 972;

export const Pop: React.FC<DesignProps> = (p) => {
  useFontsReady(["400 90px 'Dela Gothic One'", "900 56px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = PALETTES[p.variant % PALETTES.length];
  const progress = Math.min(1, frame / Math.max(1, p.durationInFrames - 1));
  const tilt = p.seed % 2 ? -1.3 : 1.1;

  const cardH = Math.round(CARD_W / p.aspect);
  const cardTop = 618;
  const cardBottom = cardTop + cardH;

  const titleTop = 214;
  const titleH = cardTop - titleTop - 40;
  const titleW = 1080 - 2 * SAFE.left;
  const titleSize = fitRich(p.title, titleW, titleH, {max: 112, min: 54, lineHeight: 1.22, widthFactor: 1.1});
  const titlePop = spring({frame, fps: p.fps, config: {damping: 11, stiffness: 170}});
  const cardIn = spring({frame: frame - 4, fps: p.fps, config: {damping: 13, stiffness: 150}});

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - SAFE.left;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 170, {max: 58, min: 38, lineHeight: 1.32}) : 58;
  const subPop = sub.entry ? interpolate(sub.local, [0, 5], [0.88, 1], {extrapolateRight: "clamp"}) : 1;

  const punchTop = 1444;
  const punchW = SAFE.right - SAFE.left - 70;
  const punchSize = fitRich(p.punchline, punchW, SAFE.bottom - punchTop - 50, {max: 54, min: 34, lineHeight: 1.3});

  const reaction = useReaction(p.reactions);
  const burst = reaction.entry ? spring({frame: reaction.local, fps: p.fps, config: {damping: 9, stiffness: 220}}) : 0;

  return (
    <AbsoluteFill style={{background: c.bg, color: INK, overflow: "hidden"}}>
      {/* Halftone in two corners */}
      <AbsoluteFill
        style={{
          backgroundImage: "radial-gradient(circle, rgba(0,0,0,0.16) 26%, transparent 28%)",
          backgroundSize: "30px 30px",
          WebkitMaskImage: "linear-gradient(135deg, black 0%, transparent 30%, transparent 70%, black 100%)",
          maskImage: "linear-gradient(135deg, black 0%, transparent 30%, transparent 70%, black 100%)",
        }}
      />

      {/* Progress */}
      <div style={{position: "absolute", top: 92, left: SAFE.left, right: SAFE.left, height: 16, border: `4px solid ${INK}`, background: "#fff"}}>
        <div style={{width: `${progress * 100}%`, height: "100%", background: c.hot}} />
      </div>

      {/* Source sticker */}
      <div style={{position: "absolute", top: 136, left: 0, right: 0, display: "flex", justifyContent: "center"}}>
        <div
          style={{
            maxWidth: 820,
            background: INK,
            color: c.bg,
            fontFamily: FONT.sans,
            fontWeight: 900,
            fontSize: 26,
            padding: "8px 22px",
            borderRadius: 999,
            transform: `rotate(${-tilt}deg)`,
            ...ellipsis,
          }}
        >
          {p.sourceTitle}
        </div>
      </div>

      {/* Headline */}
      <div
        style={{
          position: "absolute",
          top: titleTop,
          left: SAFE.left,
          width: titleW,
          height: titleH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          textAlign: "center",
          fontFamily: FONT.dela,
          fontSize: titleSize,
          lineHeight: 1.22,
          transform: `scale(${interpolate(titlePop, [0, 1], [0.93, 1])})`,
          ...jpWrap,
        }}
      >
        <RichLines
          rich={p.title}
          hlStyle={(i) => ({
            display: "inline-block",
            color: c.hot,
            ...strokeText(Math.max(6, titleSize * 0.09), INK),
            transform: `rotate(${i % 2 ? 2.5 : -2.5}deg)`,
            margin: "0 0.06em",
          })}
        />
      </div>

      {/* Clip card */}
      <div
        style={{
          position: "absolute",
          top: cardTop,
          left: CARD_X,
          width: CARD_W,
          height: cardH,
          border: `8px solid ${INK}`,
          boxShadow: `16px 16px 0 ${INK}`,
          background: "#000",
          transform: `rotate(${tilt}deg) scale(${interpolate(cardIn, [0, 1], [0.96, 1])})`,
        }}
      >
        <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
      </div>

      {reaction.entry ? (
        <div
          style={{
            position: "absolute",
            top: cardTop + cardH * 0.08,
            right: 4,
            width: 430,
            height: 250,
            transform: `rotate(${tilt > 0 ? 7 : -7}deg) scale(${burst})`,
            opacity: entryOpacity(reaction.local, reaction.length, 6),
          }}
        >
          <svg viewBox="0 0 430 250" width="430" height="250" style={{position: "absolute", inset: 0}}>
            <polygon points={starburst(215, 125, 212, 168, 18)} fill={c.hot} stroke={INK} strokeWidth="8" strokeLinejoin="round" />
          </svg>
          <div
            style={{
              position: "absolute",
              inset: "0 56px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              fontFamily: FONT.dela,
              fontSize: Math.max(26, Math.min(40, Math.floor(300 / Math.max(1, [...reaction.entry.text].length) / 1.0))),
              ...jpWrap,
              lineHeight: 1.2,
              color: "#fff",
              ...strokeText(6, INK),
            }}
          >
            {reaction.entry.text}
          </div>
        </div>
      ) : null}

      {/* Manga-style outlined subtitle under the card */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            top: cardBottom + 30,
            left: SAFE.left,
            width: subW,
            textAlign: "center",
            fontFamily: FONT.sans,
            fontWeight: 900,
            fontSize: subSize,
            lineHeight: 1.32,
            color: "#fff",
            ...strokeText(Math.round(subSize * 0.2), INK),
            transform: `scale(${subPop})`,
            opacity: entryOpacity(sub.local, sub.length, 3),
            ...jpWrap,
          }}
        >
          {sub.entry.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}

      {/* Punchline speech bubble */}
      <div style={{position: "absolute", top: punchTop, left: SAFE.left + 10, width: punchW + 50}}>
        <div style={{position: "absolute", top: -24, left: 70, width: 0, height: 0, borderLeft: "22px solid transparent", borderRight: "22px solid transparent", borderBottom: `28px solid ${INK}`}} />
        <div
          style={{
            background: INK,
            color: "#fff",
            borderRadius: 36,
            padding: "20px 34px 22px",
            fontFamily: FONT.sans,
            fontWeight: 900,
            fontSize: punchSize,
            lineHeight: 1.3,
            textAlign: "center",
            ...jpWrap,
          }}
        >
          <RichLines rich={p.punchline} hlStyle={() => ({color: c.bg})} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const starburst = (cx: number, cy: number, rx: number, ry: number, points: number) => {
  const out: string[] = [];
  for (let i = 0; i < points * 2; i++) {
    const a = (Math.PI * i) / points;
    const r = i % 2 === 0 ? 1 : 0.72;
    out.push(`${(cx + Math.cos(a) * rx * r).toFixed(1)},${(cy + Math.sin(a) * ry * r).toFixed(1)}`);
  }
  return out.join(" ");
};
