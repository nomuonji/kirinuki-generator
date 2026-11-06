import React from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, useCurrentFrame} from "remotion";
import {
  DesignProps,
  FONT,
  RichLines,
  SAFE,
  allText,
  clock,
  ellipsis,
  entryOpacity,
  fitRich,
  jpWrap,
  totalChars,
  useFontsReady,
  useReaction,
  useSubtitle,
} from "../shared";

/** 発言ログ: a dark debate console. The question is posted up front, subtitles stream in as typed log lines. */
const PALETTES = [
  {accent: "#3DFF8F", rgb: "61,255,143"},
  {accent: "#FFB224", rgb: "255,178,36"},
  {accent: "#45D8FF", rgb: "69,216,255"},
];

export const TERMINAL_VARIANTS = PALETTES.length;

const BG = "#0A0C0F";
const DIM = "#7D8895";

export const Terminal: React.FC<DesignProps> = (p) => {
  useFontsReady(["400 30px 'DotGothic16'", "900 60px 'Noto Sans JP'", "800 48px 'Noto Sans JP'"], allText(p));
  const frame = useCurrentFrame();
  const c = PALETTES[p.variant % PALETTES.length];
  const progress = Math.min(1, frame / Math.max(1, p.durationInFrames - 1));
  const blink = Math.floor(frame / 15) % 2 === 0;

  const videoH = Math.round(1080 / p.aspect);
  const videoTop = 608;
  const videoBottom = videoTop + videoH;

  const titleTop = 230;
  const titleH = videoTop - titleTop - 40;
  const titleW = SAFE.right - SAFE.left - 40;
  const qWidth = 84;
  const titleSize = fitRich(p.title, titleW - qWidth, titleH, {max: 96, min: 50, lineHeight: 1.3});

  const sub = useSubtitle(p.subtitles);
  const subW = SAFE.right - SAFE.left - 60;
  const subSize = sub.entry ? fitRich(sub.entry.text, subW, 160, {max: 54, min: 34, lineHeight: 1.4}) : 50;
  const subChars = sub.entry ? totalChars(sub.entry.text) : 0;
  const subTyped = sub.entry ? interpolate(sub.local, [0, Math.min(10, sub.length / 3)], [0, subChars], {extrapolateRight: "clamp"}) : 0;

  const punchTop = 1428;
  const punchW = SAFE.right - SAFE.left - 64;
  const punchSize = fitRich(p.punchline, punchW, SAFE.bottom - punchTop - 100, {max: 58, min: 36, lineHeight: 1.32});

  const reaction = useReaction(p.reactions);
  const slide = reaction.entry ? interpolate(reaction.local, [0, 7], [-60, 0], {extrapolateRight: "clamp"}) : 0;

  const blocks = 24;
  const filled = Math.round(progress * blocks);

  return (
    <AbsoluteFill style={{background: BG, color: "#F2F5F7"}}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(rgba(${c.rgb},0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(${c.rgb},0.06) 1px, transparent 1px)`,
          backgroundSize: "54px 54px",
        }}
      />
      <AbsoluteFill style={{background: "radial-gradient(ellipse at 50% 40%, transparent 40%, rgba(0,0,0,0.65) 100%)"}} />

      {/* Status header */}
      <div style={{position: "absolute", top: SAFE.top + 10, left: SAFE.left, right: 60, fontFamily: FONT.dot, fontSize: 30, color: c.accent, display: "flex", alignItems: "center", gap: 18}}>
        <span style={{display: "inline-block", width: 18, height: 18, borderRadius: 99, background: "#FF3B3B", opacity: blink ? 1 : 0.25}} />
        <span>REC</span>
        <span style={{color: DIM}}>|</span>
        <span>
          {clock(frame, p.fps)} / {clock(p.durationInFrames, p.fps)}
        </span>
      </div>
      <div style={{position: "absolute", top: SAFE.top + 56, left: SAFE.left, right: 60, fontFamily: FONT.dot, fontSize: 24, color: DIM, ...ellipsis}}>
        src: {p.sourceTitle}
      </div>
      <div style={{position: "absolute", top: 202, left: SAFE.left, display: "flex", gap: 5}}>
        {Array.from({length: blocks}).map((_, i) => (
          <div key={i} style={{width: 34, height: 10, background: i < filled ? c.accent : "#1C232B"}} />
        ))}
      </div>

      {/* Question: fully readable from frame 0 (first frame is the hook) */}
      <div style={{position: "absolute", top: titleTop, left: SAFE.left, width: titleW + 40, height: titleH, display: "flex", gap: 18}}>
        <div style={{fontFamily: FONT.dot, fontSize: 60, color: c.accent, lineHeight: 1.45, width: qWidth - 18, flexShrink: 0}}>Q.</div>
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            fontFamily: FONT.sans,
            fontWeight: 900,
            fontSize: titleSize,
            lineHeight: 1.3,
            ...jpWrap,
          }}
        >
          <RichLines rich={p.title} hlStyle={() => hl(c.accent)} />
        </div>
      </div>

      {/* Clip in a viewfinder */}
      <div style={{position: "absolute", top: videoTop, left: 0, width: 1080, height: videoH, background: "#000"}}>
        <OffthreadVideo src={p.videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
        <AbsoluteFill style={{backgroundImage: "repeating-linear-gradient(0deg, rgba(0,0,0,0.12) 0 2px, transparent 2px 5px)"}} />
        {(["tl", "tr", "bl", "br"] as const).map((k) => (
          <Corner key={k} pos={k} color={c.accent} />
        ))}
        {reaction.entry ? (
          <div
            style={{
              position: "absolute",
              left: 34,
              bottom: 34,
              maxWidth: 760,
              padding: "12px 22px",
              background: "rgba(5,7,9,0.82)",
              borderLeft: `6px solid ${c.accent}`,
              transform: `translateX(${slide}px)`,
              opacity: entryOpacity(reaction.local, reaction.length, 6),
            }}
          >
            <div style={{fontFamily: FONT.dot, fontSize: 22, color: c.accent}}>[comment]</div>
            <div style={{fontFamily: FONT.sans, fontWeight: 800, fontSize: 36, lineHeight: 1.3}}>{reaction.entry.text}</div>
          </div>
        ) : null}
      </div>

      {/* Subtitle log line */}
      {sub.entry ? (
        <div
          style={{
            position: "absolute",
            top: videoBottom + 28,
            left: SAFE.left,
            width: SAFE.right - SAFE.left,
            display: "flex",
            gap: 16,
            opacity: entryOpacity(sub.local, sub.length, 3),
          }}
        >
          <span style={{fontFamily: FONT.dot, fontSize: subSize, color: c.accent, lineHeight: 1.4}}>&gt;</span>
          <div style={{fontFamily: FONT.sans, fontWeight: 800, fontSize: subSize, lineHeight: 1.4, ...jpWrap}}>
            <TypedLines text={sub.entry.text} chars={subTyped} />
            <span
              style={{
                display: "inline-block",
                width: Math.round(subSize * 0.5),
                height: Math.round(subSize * 0.9),
                marginLeft: 6,
                verticalAlign: "-0.12em",
                background: c.accent,
                opacity: blink ? 1 : 0,
              }}
            />
          </div>
        </div>
      ) : null}

      {/* Conclusion panel */}
      <div
        style={{
          position: "absolute",
          top: punchTop,
          left: SAFE.left,
          width: SAFE.right - SAFE.left,
          padding: "18px 30px 24px",
          border: `3px solid ${c.accent}`,
          background: `rgba(${c.rgb},0.07)`,
        }}
      >
        <div style={{fontFamily: FONT.dot, fontSize: 28, color: c.accent, marginBottom: 8}}>// 結論</div>
        <div style={{fontFamily: FONT.sans, fontWeight: 900, fontSize: punchSize, lineHeight: 1.32, ...jpWrap}}>
          <RichLines rich={p.punchline} hlStyle={() => ({color: c.accent})} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const hl = (accent: string): React.CSSProperties => ({
  background: accent,
  color: BG,
  padding: "0 0.12em",
  margin: "0 0.04em",
  WebkitBoxDecorationBreak: "clone",
  boxDecorationBreak: "clone",
});

const TypedLines: React.FC<{text: string; chars: number}> = ({text, chars}) => {
  let budget = Math.floor(chars);
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => {
        const cs = [...line];
        const shown = cs.slice(0, Math.max(0, budget)).join("");
        budget -= cs.length;
        const last = i === lines.length - 1;
        return last ? <span key={i}>{shown}</span> : <div key={i}>{shown}</div>;
      })}
    </>
  );
};

const Corner: React.FC<{pos: "tl" | "tr" | "bl" | "br"; color: string}> = ({pos, color}) => {
  const arm = 64;
  const t = 6;
  const inset = 18;
  const v = pos[0] === "t" ? {top: inset} : {bottom: inset};
  const h = pos[1] === "l" ? {left: inset} : {right: inset};
  return (
    <div style={{position: "absolute", width: arm, height: arm, ...v, ...h}}>
      <div style={{position: "absolute", [pos[0] === "t" ? "top" : "bottom"]: 0, left: 0, width: arm, height: t, background: color}} />
      <div style={{position: "absolute", [pos[1] === "l" ? "left" : "right"]: 0, top: 0, width: t, height: arm, background: color}} />
    </div>
  );
};
