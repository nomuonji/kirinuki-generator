import React from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, useCurrentFrame} from "remotion";
import {
  DesignProps,
  FONT,
  RichLines,
  SAFE,
  allText,
  clock,
  entryOpacity,
  fitRich,
  jpWrap,
  parseRich,
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/** シネマ: quiet, dark and spacious. Blur-in headline, subtitles without boxes, the punchline as a quoted line. */
const PALETTES = [
  {accent: "#E9C46A", glow: "rgba(233,196,106,0.10)"},
  {accent: "#FF6B5E", glow: "rgba(255,107,94,0.10)"},
];

export const CINEMA_VARIANTS = PALETTES.length;

export const Cinema: React.FC<DesignProps> = (p) => {
  useFontsReady(["900 80px 'Zen Kaku Gothic New'", "700 48px 'Zen Kaku Gothic New'", "500 28px 'Zen Kaku Gothic New'"], allText(p));
  const frame = useCurrentFrame();
  const c = PALETTES[p.variant % PALETTES.length];
  const progress = Math.min(1, frame / Math.max(1, p.durationInFrames - 1));

  const videoH = Math.round(1080 / p.aspect);
  const videoTop = 616;
  const videoBottom = videoTop + videoH;

  const titleTop = 236;
  const titleH = videoTop - titleTop - 44;
  const titleW = SAFE.right - SAFE.left + 20;
  const titleSize = fitRich(p.title, titleW, titleH, {max: 92, min: 48, lineHeight: 1.34, widthFactor: 1.08});
  const titleLines = parseRich(p.title);

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - SAFE.left;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 160, {max: 54, min: 34, lineHeight: 1.45}) : 50;

  const punchTop = 1448;
  const punchW = SAFE.right - SAFE.left - 120;
  const punchSize = fitRich(p.punchline, punchW, SAFE.bottom - punchTop - 30, {max: 56, min: 34, lineHeight: 1.35});

  const reaction = useReaction(p.reactions);

  return (
    <AbsoluteFill style={{background: "#0A0A0B", color: "#F4F1EA"}}>
      <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 32%, ${c.glow}, transparent 60%)`}} />

      <div style={{position: "absolute", top: SAFE.top + 46, left: 0, right: 0, textAlign: "center", fontFamily: FONT.zen, fontWeight: 500, fontSize: 28, letterSpacing: "0.5em", color: "#8F8C86"}}>
        ― 本日の論点 ―
      </div>

      {/* Headline: each line resolves out of a blur */}
      <div
        style={{
          position: "absolute",
          top: titleTop,
          left: (1080 - titleW) / 2 - 20,
          width: titleW,
          height: titleH,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          textAlign: "center",
          fontFamily: FONT.zen,
          fontWeight: 900,
          fontSize: titleSize,
          lineHeight: 1.34,
          letterSpacing: "0.03em",
          ...jpWrap,
        }}
      >
        {titleLines.map((_, i) => {
          const t = interpolate(frame, [i * 4, i * 4 + 14], [0.55, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          const single = parseRichLine(p.title, i);
          return (
            <div key={i} style={{filter: `blur(${(1 - t) * 8}px)`, opacity: 0.4 + 0.6 * t, transform: `translateY(${(1 - t) * 12}px)`}}>
              <RichLines rich={single} hlStyle={() => ({color: c.accent})} />
            </div>
          );
        })}
      </div>

      {/* Clip with soft edges */}
      <div
        style={{
          position: "absolute",
          top: videoTop,
          left: 0,
          width: 1080,
          height: videoH,
          WebkitMaskImage: "linear-gradient(to bottom, transparent 0, black 7%, black 93%, transparent 100%)",
          maskImage: "linear-gradient(to bottom, transparent 0, black 7%, black 93%, transparent 100%)",
        }}
      >
        <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
        {reaction.entry ? (
          <div
            style={{
              position: "absolute",
              top: 46,
              left: 40,
              maxWidth: 700,
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "12px 26px",
              borderRadius: 999,
              background: "rgba(10,10,11,0.62)",
              border: "1px solid rgba(255,255,255,0.22)",
              fontFamily: FONT.zen,
              fontWeight: 700,
              fontSize: 32,
              opacity: entryOpacity(reaction.local, reaction.length, 8),
            }}
          >
            <span style={{width: 12, height: 12, borderRadius: 99, background: c.accent, flexShrink: 0}} />
            {reaction.entry.text}
          </div>
        ) : null}
      </div>

      {/* Timeline */}
      <div style={{position: "absolute", top: videoBottom + 14, left: SAFE.left, right: SAFE.left, height: 2, background: "rgba(255,255,255,0.14)"}}>
        <div style={{width: `${progress * 100}%`, height: "100%", background: c.accent}} />
      </div>
      <div style={{position: "absolute", top: videoBottom + 24, right: SAFE.left, fontFamily: FONT.zen, fontWeight: 500, fontSize: 22, color: "#77746E", letterSpacing: "0.1em"}}>
        {clock(frame, p.fps)}
      </div>

      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            top: videoBottom + 56,
            left: SAFE.left,
            width: subW,
            textAlign: "center",
            fontFamily: FONT.zen,
            fontWeight: 700,
            fontSize: subSize,
            lineHeight: 1.45,
            textShadow: "0 2px 14px rgba(0,0,0,0.9)",
            opacity: entryOpacity(sub.local, sub.length, 5),
            ...jpWrap,
          }}
        >
          {sub.entry.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      ) : null}

      {/* Quoted punchline */}
      <div style={{position: "absolute", top: punchTop, left: SAFE.left + 30, width: punchW + 60, textAlign: "center"}}>
        <span style={{position: "absolute", top: -14, left: -18, fontFamily: FONT.zen, fontWeight: 900, fontSize: 76, color: c.accent, lineHeight: 1}}>「</span>
        <span style={{position: "absolute", bottom: -14, right: -18, fontFamily: FONT.zen, fontWeight: 900, fontSize: 76, color: c.accent, lineHeight: 1}}>」</span>
        <div style={{padding: "10px 30px", fontFamily: FONT.zen, fontWeight: 900, fontSize: punchSize, lineHeight: 1.35, ...jpWrap}}>
          <RichLines rich={p.punchline} hlStyle={() => ({color: c.accent})} />
        </div>
      </div>

      {/* Static film grain. Animated grain looks like mush after YouTube's re-encode and
          bloats the bitrate (12 s went from ~2 MB to 32 MB), so the pattern stays fixed per clip. */}
      <AbsoluteFill style={{opacity: 0.07, mixBlendMode: "screen", pointerEvents: "none"}}>
        <svg viewBox="0 0 360 640" width="1080" height="1920" preserveAspectRatio="none">
          <filter id="grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="1" seed={p.seed % 997} />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width="360" height="640" filter="url(#grain)" />
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Re-serialise one parsed line back to rich text so it can be animated on its own. */
const parseRichLine = (rich: string, index: number) =>
  (parseRich(rich)[index] ?? []).map((s) => (s.hl ? `**${s.text}**` : s.text)).join("");
