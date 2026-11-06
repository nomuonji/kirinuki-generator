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

/** 号外: a newspaper page. Mincho headline with 傍点 emphasis, the clip as the front-page photo, subtitles as its caption. */
const PALETTES = [
  {paper: "#F2EDE1", ink: "#1B1814", accent: "#C8102E"},
  {paper: "#ECEEE8", ink: "#13181D", accent: "#1F4E9C"},
];

export const GOUGAI_VARIANTS = PALETTES.length;

const PHOTO_X = 60;
const PHOTO_W = 960;

export const Gougai: React.FC<DesignProps> = (p) => {
  useFontsReady(["800 80px 'Shippori Mincho B1'", "800 48px 'Noto Sans JP'", "900 48px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = PALETTES[p.variant % PALETTES.length];
  const progress = Math.min(1, frame / Math.max(1, p.durationInFrames - 1));

  const photoH = Math.round(PHOTO_W / p.aspect);
  const photoTop = 604;
  const photoBottom = photoTop + photoH;

  const titleTop = 226;
  const titleH = photoTop - titleTop - 34;
  const titleW = SAFE.right - SAFE.left + 60;
  const titleSize = fitRich(p.title, titleW, titleH, {max: 108, min: 54, lineHeight: 1.32});

  const sub = useSubtitle(p.subtitles);
  const subTop = photoBottom + 22;
  const subW = SAFE.right - SAFE.left - 56;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 150, {max: 54, min: 34, lineHeight: 1.4}) : 50;

  const punchTop = 1418;
  const punchW = SAFE.right - SAFE.left - 40;
  const punchSize = fitRich(p.punchline, punchW, SAFE.bottom - punchTop - 64, {max: 66, min: 38, lineHeight: 1.3});

  const reaction = useReaction(p.reactions);
  const stamp = reaction.entry
    ? spring({frame: reaction.local, fps: p.fps, config: {damping: 14, stiffness: 260, mass: 0.6}})
    : 0;

  return (
    <AbsoluteFill style={{background: c.paper, color: c.ink}}>
      <svg viewBox="0 0 540 960" width="1080" height="1920" preserveAspectRatio="none" style={{position: "absolute", inset: 0, opacity: 0.14, mixBlendMode: "multiply"}}>
        <filter id="paper" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.75" numOctaves="2" seed={p.seed % 997} />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="540" height="960" filter="url(#paper)" />
      </svg>

      {/* Masthead */}
      <div style={{position: "absolute", top: SAFE.top + 8, left: SAFE.left, right: 60, display: "flex", alignItems: "center", gap: 22}}>
        <div
          style={{
            background: c.accent,
            color: c.paper,
            fontFamily: FONT.mincho,
            fontWeight: 800,
            fontSize: 44,
            lineHeight: 1,
            padding: "12px 16px 14px",
            letterSpacing: 6,
          }}
        >
          論点
        </div>
        <div style={{flex: 1, minWidth: 0}}>
          <div style={{fontFamily: FONT.sans, fontWeight: 800, fontSize: 22, letterSpacing: 6, opacity: 0.55}}>KIRINUKI EDITION</div>
          <div style={{fontFamily: FONT.sans, fontWeight: 800, fontSize: 27, marginTop: 4, ...ellipsis}}>{p.sourceTitle}</div>
        </div>
      </div>
      <div style={{position: "absolute", top: 198, left: SAFE.left, right: 60, height: 6, background: c.ink}} />
      <div style={{position: "absolute", top: 198, left: SAFE.left, width: (1080 - SAFE.left - 60) * progress, height: 6, background: c.accent}} />
      <div style={{position: "absolute", top: 208, left: SAFE.left, right: 60, height: 2, background: c.ink}} />

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
          fontFamily: FONT.mincho,
          fontWeight: 800,
          fontSize: titleSize,
          lineHeight: 1.32,
          letterSpacing: "0.02em",
          ...jpWrap,
        }}
      >
        <RichLines
          rich={p.title}
          hlStyle={() => ({
            color: c.accent,
            // 傍点 (emphasis dots) — the editorial way Japanese print stresses a word.
            WebkitTextEmphasis: `filled sesame ${c.accent}`,
            textEmphasis: `filled sesame ${c.accent}`,
          } as React.CSSProperties)}
        />
      </div>

      {/* Front-page photo */}
      <div
        style={{
          position: "absolute",
          top: photoTop,
          left: PHOTO_X,
          width: PHOTO_W,
          height: photoH,
          outline: `3px solid ${c.ink}`,
          outlineOffset: 8,
          background: "#000",
        }}
      >
        <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "contain", filter: "contrast(1.04) saturate(0.92)"}} />
      </div>

      {/* Caption = subtitle */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            top: subTop,
            left: SAFE.left,
            width: SAFE.right - SAFE.left,
            display: "flex",
            gap: 14,
            opacity: entryOpacity(sub.local, sub.length, 4),
            fontFamily: FONT.sans,
            fontWeight: 800,
            fontSize: subSize,
            lineHeight: 1.4,
          }}
        >
          <span style={{color: c.accent, flexShrink: 0}}>▲</span>
          <div style={jpWrap}>
            {sub.entry.text.split("\n").map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Pull quote */}
      <div style={{position: "absolute", top: punchTop, left: SAFE.left, width: punchW + 40, display: "flex", gap: 24}}>
        <div style={{width: 12, background: c.accent, flexShrink: 0}} />
        <div>
          <div style={{fontFamily: FONT.sans, fontWeight: 900, fontSize: 26, letterSpacing: 10, color: c.accent, marginBottom: 10}}>要点</div>
          <div style={{fontFamily: FONT.mincho, fontWeight: 800, fontSize: punchSize, lineHeight: 1.3, ...jpWrap}}>
            <RichLines rich={p.punchline} hlStyle={() => ({color: c.accent})} />
          </div>
        </div>
      </div>

      {/* Reaction = editor's stamp */}
      {reaction.entry ? (
        <div
          style={{
            position: "absolute",
            top: photoTop - 30,
            right: 46,
            maxWidth: 520,
            padding: "14px 22px",
            border: `5px solid ${c.accent}`,
            borderRadius: 10,
            background: `${c.paper}EE`,
            color: c.accent,
            fontFamily: FONT.sans,
            fontWeight: 900,
            fontSize: 36,
            lineHeight: 1.25,
            transform: `rotate(${p.seed % 2 ? -5 : 4}deg) scale(${interpolate(stamp, [0, 1], [1.7, 1])})`,
            opacity: Math.min(stamp * 1.5, entryOpacity(reaction.local, reaction.length, 6)),
            display: "flex",
            gap: 14,
            alignItems: "center",
          }}
        >
          <span style={{fontSize: 26, border: `3px solid ${c.accent}`, borderRadius: 999, padding: "4px 10px", flexShrink: 0}}>注</span>
          <span>{reaction.entry.text}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
