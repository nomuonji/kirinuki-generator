import React from "react";
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

import {ReactionOverlay, ReactionTimelineEntry} from "./ReactionOverlay";

import {SubtitleOverlay, SubtitleEntry} from './SubtitleOverlay';

type VideoWithBandsProps = {
  videoFileName: string;
  topText: string;
  bottomText: string;
  topRichText?: string;
  bottomRichText?: string;
  /** e.g. 16/9, 4/3. Defaults to 16/9 when omitted. */
  sourceAspect?: number;
  reactionTimeline?: ReactionTimelineEntry[];
  subtitleTimeline?: SubtitleEntry[];
};

const textBase: React.CSSProperties = {
  fontFamily: "'Rounded Mplus 1c', 'Hiragino Maru Gothic ProN', 'Yu Gothic', sans-serif",
  color: "white",
  fontWeight: "900",
  textAlign: "center",
  textShadow: "0 0 12px rgba(0,0,0,0.8)",
  lineHeight: 1.3,
  width: "100%",
  wordBreak: "break-word",
  whiteSpace: "pre-wrap",
  letterSpacing: 1.5,
  paddingLeft: 40,
  paddingRight: 40,
};

const highlightStyle: React.CSSProperties = {
  background: "linear-gradient(135deg, #FFF4B7 0%, #FFD1DC 55%, #CDE9FF 100%)",
  color: "#31124E",
  padding: "0.1em 0.35em",
  borderRadius: "0.35em",
  boxShadow: "0 6px 16px rgba(24, 0, 40, 0.3)",
};

const normalizeRichSource = (value: string): string =>
  value
    .replace(/\r\n?/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\u2028/g, "\n")
    .replace(/\u2029/g, "\n")
    .trim();

const renderRichText = (richText?: string, fallback?: string): React.ReactNode => {
  const candidateRich = typeof richText === "string" ? normalizeRichSource(richText) : "";
  const candidateFallback = typeof fallback === "string" ? normalizeRichSource(fallback) : "";
  const source = candidateRich || candidateFallback;
  if (!source) {
    return "";
  }

  const lineStyle: React.CSSProperties = {
    display: "block",
    marginBottom: "0.25em",
  };

  const textChunkStyle: React.CSSProperties = {
    display: "inline",
    lineHeight: "1.45",
  };

  return source.split("\n").map((line, lineIndex) => (
    <div key={`line-${lineIndex}`} style={lineStyle}>
      {line.split(/(\*\*[^*]+\*\*)/g).map((chunk, chunkIndex) => {
        if (/^\*\*[^*]+\*\*$/.test(chunk)) {
          const content = chunk.slice(2, -2);
          return (
            <span key={`highlight-${lineIndex}-${chunkIndex}`} style={highlightStyle}>
              {content}
            </span>
          );
        }
        return (
          <span key={`text-${lineIndex}-${chunkIndex}`} style={textChunkStyle}>
            {chunk}
          </span>
        );
      })}
    </div>
  ));
};

/**
 * Animated gradient and confetti-style blobs for a playful backdrop.
 */
const AnimatedBackground: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / Math.max(fps, 1);

  const angle = 35 + Math.sin(t * 1.1) * 25;
  const accent1X = 18 + Math.sin(t * 0.7) * 6;
  const accent1Y = 22 + Math.cos(t * 0.9) * 7;
  const accent2X = 78 + Math.cos(t * 0.8) * 7;
  const accent2Y = 18 + Math.sin(t * 1.3) * 6;
  const accent3X = 50 + Math.sin(t * 0.6) * 12;
  const accent3Y = 82 + Math.cos(t * 0.75) * 8;

  const backgroundImage = `
    radial-gradient(circle at ${accent1X}% ${accent1Y}%, rgba(255,255,255,0.35), transparent 55%),
    radial-gradient(circle at ${accent2X}% ${accent2Y}%, rgba(255,255,255,0.25), transparent 60%),
    radial-gradient(circle at ${accent3X}% ${accent3Y}%, rgba(255,255,255,0.28), transparent 65%),
    linear-gradient(${angle}deg, #FF9A9E 0%, #FECFEF 35%, #A1C4FD 70%, #C2E9FB 100%)
  `;

  const confettiPalette = [
    {color: "#FFD166", size: 28, baseX: 12, baseY: 22, ampX: 10, ampY: 12, freqX: 1.05, freqY: 0.85},
    {color: "#9CFFFA", size: 22, baseX: 52, baseY: 16, ampX: 14, ampY: 10, freqX: 0.8, freqY: 1.1},
    {color: "#FF9CEE", size: 26, baseX: 82, baseY: 28, ampX: 9, ampY: 14, freqX: 1.2, freqY: 1.4},
    {color: "#B5F44A", size: 24, baseX: 28, baseY: 72, ampX: 11, ampY: 10, freqX: 0.9, freqY: 0.7},
    {color: "#FFC6FF", size: 20, baseX: 66, baseY: 78, ampX: 13, ampY: 9, freqX: 1.1, freqY: 0.95},
  ];

  return (
    <AbsoluteFill style={{zIndex: 0, overflow: "hidden", pointerEvents: "none"}}>
      <div
        style={{
          position: "absolute",
          inset: "-6%",
          backgroundImage,
          backgroundRepeat: "no-repeat",
          backgroundSize: "160% 160%, 140% 140%, 160% 160%, 100% 100%",
          backgroundBlendMode: "screen, screen, screen, normal",
          filter: "saturate(1.08)",
        }}
      />
      {confettiPalette.map((piece, index) => {
        const x = piece.baseX + Math.sin(t * piece.freqX + index) * piece.ampX;
        const y = piece.baseY + Math.cos(t * piece.freqY + index) * piece.ampY;
        const rotation = Math.sin(t * (0.8 + index * 0.15)) * 45;

        return (
          <div
            key={`confetti-${index}`}
            style={{
              position: "absolute",
              left: `${x}%`,
              top: `${y}%`,
              width: piece.size,
              height: piece.size * 0.65,
              borderRadius: index % 2 === 0 ? "50% 40% 55% 45%" : "35% 65% 45% 55%",
              backgroundColor: piece.color,
              opacity: 0.55,
              transform: `rotate(${rotation}deg)`,
              boxShadow: "0 12px 24px rgba(0,0,0,0.08)",
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

export const VideoWithBands: React.FC<VideoWithBandsProps> = ({
  videoFileName,
  topText,
  bottomText,
  topRichText,
  bottomRichText,
  sourceAspect = 16 / 9,
  reactionTimeline = [],
  subtitleTimeline = [],
}) => {
  const {width: W, height: H} = useVideoConfig();

  // Height of the video when scaled using object-fit "contain"
  // For a 9:16 canvas with a 16:9 source: videoHeight = W / sourceAspect
  const videoHeight = W / sourceAspect;

  // Height of the resulting top/bottom letterbox bands
  const bandH = Math.max(0, Math.round((H - videoHeight) / 2));

  // Scale text size relative to band height
  const topFont = `clamp(28px, ${Math.round(bandH * 0.64)}px, 74px)`;
  const bottomFont = topFont;

  const safePath = videoFileName
    .split("\\")
    .join("/")
    .replace(/^public\//, "");
  const videoSrc = staticFile(safePath);

  const topContent = renderRichText(topRichText, topText);
  const bottomContent = renderRichText(bottomRichText, bottomText);

  const hasReactions = reactionTimeline.length > 0;
  const hasSubtitles = subtitleTimeline.length > 0;

  const reactionBottomOffset = hasReactions
    ? Math.max(120, bandH + Math.max(36, Math.round(bandH * 0.1)))
    : 0;

  const panelBaseStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "18px 40px",
    borderRadius: 38,
    maxWidth: "92%",
    background: "linear-gradient(135deg, rgba(26,16,58,0.94) 0%, rgba(52,26,92,0.82) 55%, rgba(90,70,180,0.38) 100%)",
    border: "1px solid rgba(168,148,255,0.35)",
    backdropFilter: "blur(16px)",
    boxShadow: "0 18px 38px rgba(18,6,48,0.52)",
    margin: "0 auto",
    position: "relative",
    overflow: "hidden",
  };

  const topPanelStyle: React.CSSProperties = {
    ...panelBaseStyle,
    background: "linear-gradient(135deg, rgba(30,18,60,0.95) 0%, rgba(68,32,106,0.86) 60%, rgba(144,90,226,0.42) 100%)",
  };

  const bottomPanelStyle: React.CSSProperties = {
    ...panelBaseStyle,
    padding: "20px 46px",
    borderRadius: 44,
    background: "linear-gradient(140deg, rgba(18,10,32,0.96) 0%, rgba(48,24,80,0.86) 48%, rgba(34,134,214,0.42) 100%)",
    border: "1px solid rgba(160,210,255,0.38)",
    boxShadow: "0 24px 52px rgba(10,4,30,0.58)",
  };

  const topTextStyle: React.CSSProperties = {
    ...textBase,
    fontSize: topFont,
    width: "auto",
    textShadow: "0 10px 28px rgba(0,0,0,0.6)",
    letterSpacing: 1.4,
  };

  const bottomTextStyle: React.CSSProperties = {
    ...textBase,
    fontSize: bottomFont,
    letterSpacing: 1.6,
    textTransform: "none",
    textShadow: "0 14px 34px rgba(6,0,22,0.7)",
    width: "auto",
  };

  return (
    <AbsoluteFill>
      <AnimatedBackground />
      <AbsoluteFill style={{zIndex: 1}}>
        {/* Top overlay aligned with the top band */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: bandH,
            display: "grid",
            placeItems: "center",
            pointerEvents: "none",
          }}
        >
          <div style={topPanelStyle}>
            <div style={{...textBase, fontSize: topFont, width: "auto"}}>{topContent}</div>
          </div>
        </div>

        {/* Video centered with contain fit */}
        <div
          style={{
            position: "absolute",
            top: bandH,
            left: 0,
            right: 0,
            height: H - bandH * 2,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <OffthreadVideo src={videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
        </div>

        {hasSubtitles ? <SubtitleOverlay timeline={subtitleTimeline} /> : null}

        {hasReactions ? (
          <ReactionOverlay bottomOffset={reactionBottomOffset} timeline={reactionTimeline} />
        ) : null}

        {/* Bottom overlay aligned with the bottom band */}
        <div
          style={{
            position: "absolute",
            top: H - bandH,
            left: 0,
            right: 0,
            height: bandH,
            transform: "translateY(0)",
            display: "grid",
            placeItems: "center",
            pointerEvents: "none",
          }}
        >
          <div style={bottomPanelStyle}>
            <div style={bottomTextStyle}>{bottomContent}</div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
