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
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/** ノート: graph paper, handwritten headline with a highlighter swipe, the clip taped in like a photo, punchline on a sticky note. */
const PALETTES = [
  {paper: "#FBFAF4", grid: "rgba(110,160,205,0.30)", ink: "#1F2D57", marker: "#FFE45C", pen: "#E0453A", tape: "rgba(140,214,196,0.82)", sticky: "#FFF09A"},
  {paper: "#FFF8EE", grid: "rgba(215,160,130,0.30)", ink: "#33261B", marker: "#9EF0C0", pen: "#2F64DA", tape: "rgba(247,176,196,0.85)", sticky: "#D9F3FF"},
];

export const NOTE_VARIANTS = PALETTES.length;

const PHOTO_X = 82;
const PHOTO_W = 916;
const FRAME_PAD = 16;

export const Note: React.FC<DesignProps> = (p) => {
  useFontsReady(["400 80px 'Yusei Magic'", "800 48px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = PALETTES[p.variant % PALETTES.length];
  const progress = Math.min(1, frame / Math.max(1, p.durationInFrames - 1));
  const tilt = p.seed % 2 ? 0.9 : -0.8;

  const photoInnerW = PHOTO_W - FRAME_PAD * 2;
  const photoH = Math.round(photoInnerW / p.aspect) + FRAME_PAD * 2;
  const photoTop = 612;
  const photoBottom = photoTop + photoH;

  const titleTop = 230;
  const titleH = photoTop - titleTop - 40;
  const titleLeft = 112;
  const titleW = 1080 - titleLeft - 70;
  const titleSize = fitRich(p.title, titleW, titleH, {max: 100, min: 52, lineHeight: 1.36});

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - titleLeft;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 150, {max: 52, min: 34, lineHeight: 1.42}) : 48;

  const punchTop = 1440;
  const punchW = SAFE.right - SAFE.left - 110;
  const punchSize = fitRich(p.punchline, punchW, SAFE.bottom - punchTop - 90, {max: 54, min: 34, lineHeight: 1.32});

  const reaction = useReaction(p.reactions);
  const pop = reaction.entry ? spring({frame: reaction.local, fps: p.fps, config: {damping: 12, stiffness: 180}}) : 0;

  return (
    <AbsoluteFill style={{background: c.paper, color: c.ink}}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${c.grid} 1.5px, transparent 1.5px), linear-gradient(90deg, ${c.grid} 1.5px, transparent 1.5px)`,
          backgroundSize: "44px 44px",
          backgroundPosition: "-2px 10px",
        }}
      />
      <div style={{position: "absolute", top: 0, bottom: 0, left: 86, width: 3, background: c.pen, opacity: 0.45}} />

      {/* Washi tape with the source title */}
      <div
        style={{
          position: "absolute",
          top: SAFE.top + 18,
          left: 40,
          maxWidth: 760,
          padding: "12px 30px",
          background: c.tape,
          backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.25) 0 10px, transparent 10px 20px)",
          transform: "rotate(-2.4deg)",
          fontFamily: FONT.hand,
          fontSize: 28,
          ...ellipsis,
        }}
      >
        {p.sourceTitle}
      </div>

      {/* Handwritten headline with a highlighter */}
      <div
        style={{
          position: "absolute",
          top: titleTop,
          left: titleLeft,
          width: titleW,
          height: titleH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          fontFamily: FONT.hand,
          fontSize: titleSize,
          lineHeight: 1.36,
          ...jpWrap,
        }}
      >
        <RichLines
          rich={p.title}
          hlStyle={(i) => {
            const t = interpolate(frame, [8 + i * 8, 22 + i * 8], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
            return {
              backgroundImage: `linear-gradient(transparent 52%, ${c.marker} 52%, ${c.marker} 92%, transparent 92%)`,
              backgroundSize: `${t}% 100%`,
              backgroundRepeat: "no-repeat",
              WebkitBoxDecorationBreak: "clone",
              boxDecorationBreak: "clone",
              padding: "0 0.06em",
            };
          }}
        />
      </div>

      {/* Taped photo */}
      <div
        style={{
          position: "absolute",
          top: photoTop,
          left: PHOTO_X,
          width: PHOTO_W,
          height: photoH,
          padding: FRAME_PAD,
          background: "#fff",
          boxShadow: "0 14px 34px rgba(30,30,40,0.22)",
          transform: `rotate(${tilt}deg)`,
          boxSizing: "border-box",
        }}
      >
        <div style={{width: "100%", height: "100%", background: "#000"}}>
          <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
        </div>
        <Tape color={c.tape} style={{top: -22, left: -34, transform: "rotate(-34deg)"}} />
        <Tape color={c.tape} style={{top: -22, right: -34, transform: "rotate(32deg)"}} />
      </div>

      {reaction.entry ? (
        <div
          style={{
            position: "absolute",
            top: photoTop - 70,
            right: 44,
            maxWidth: 540,
            padding: "10px 22px",
            background: "#fff",
            boxShadow: "0 6px 14px rgba(0,0,0,0.16)",
            color: c.pen,
            fontFamily: FONT.hand,
            fontSize: 38,
            lineHeight: 1.25,
            transform: `rotate(${tilt > 0 ? -4 : 4}deg) scale(${interpolate(pop, [0, 1], [0.6, 1])})`,
            opacity: Math.min(pop * 1.4, entryOpacity(reaction.local, reaction.length, 6)),
          }}
        >
          {reaction.entry.text}
        </div>
      ) : null}

      {/* Subtitle written under the photo */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            top: photoBottom + 30,
            left: titleLeft,
            width: subW,
            fontFamily: FONT.sans,
            fontWeight: 800,
            fontSize: subSize,
            lineHeight: 1.42,
            opacity: entryOpacity(sub.local, sub.length, 4),
            ...jpWrap,
          }}
        >
          {sub.entry.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}

      {/* Sticky note */}
      <div
        style={{
          position: "absolute",
          top: punchTop,
          left: SAFE.left + 40,
          width: punchW + 70,
          padding: "16px 34px 26px",
          background: c.sticky,
          boxShadow: "0 12px 22px rgba(0,0,0,0.16)",
          transform: `rotate(${tilt > 0 ? -1.4 : 1.4}deg)`,
        }}
      >
        <div style={{fontFamily: FONT.hand, fontSize: 30, color: c.pen, marginBottom: 4}}>POINT!</div>
        <div style={{fontFamily: FONT.hand, fontSize: punchSize, lineHeight: 1.32, ...jpWrap}}>
          <RichLines rich={p.punchline} hlStyle={() => ({color: c.pen})} />
        </div>
        <div style={{position: "absolute", left: 0, bottom: 0, height: 6, width: `${progress * 100}%`, background: c.pen, opacity: 0.55}} />
      </div>
    </AbsoluteFill>
  );
};

const Tape: React.FC<{color: string; style: React.CSSProperties}> = ({color, style}) => (
  <div
    style={{
      position: "absolute",
      width: 150,
      height: 46,
      background: color,
      backgroundImage: "repeating-linear-gradient(90deg, rgba(255,255,255,0.22) 0 8px, transparent 8px 16px)",
      ...style,
    }}
  />
);
