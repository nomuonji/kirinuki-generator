import React from "react";
import {AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig, spring, interpolate} from "remotion";

import {ReactionOverlay, ReactionTimelineEntry} from "./ReactionOverlay";

import {SubtitleOverlay, SubtitleEntry} from './SubtitleOverlay';

type VideoWithBandsProps = {
  videoFileName: string;
  topText: string;
  bottomText: string;
  topRichText?: string;
  bottomRichText?: string;
  sourceVideoTitle?: string;
  /** e.g. 16/9, 4/3. Defaults to 16/9 when omitted. */
  sourceAspect?: number;
  reactionTimeline?: ReactionTimelineEntry[];
  subtitleTimeline?: SubtitleEntry[];
};

// Keyframes for the shadow animation
const animationStyles = `
  @keyframes waver-shadow {
    0% {
      box-shadow: 0 18px 38px rgba(0, 0, 0, 0.28);
      transform: translateY(0px);
    }
    50% {
      box-shadow: 0 25px 48px rgba(0, 0, 0, 0.35);
      transform: translateY(-3px);
    }
    100% {
      box-shadow: 0 18px 38px rgba(0, 0, 0, 0.28);
      transform: translateY(0px);
    }
  }
`;

const textBase: React.CSSProperties = {
  fontFamily: "'M PLUS Rounded 1c', 'Hiragino Maru Gothic ProN', 'Yu Gothic', sans-serif",
  color: "#31124E",
  fontWeight: "900",
  textAlign: "center",
  lineHeight: 1.3,
  width: "100%",
  wordBreak: "break-word",
  whiteSpace: "pre-wrap",
  letterSpacing: 1.5,
  // @ts-ignore
  paintOrder: "stroke fill",
  WebkitTextStroke: "1.5px white",
  textStroke: "1.5px white",
  textShadow: "3px 3px 5px rgba(0,0,0,0.25)",
};

const highlightStyle: React.CSSProperties = {
  display: "inline-block", // Required for transforms
  color: "#FFD700",
  // @ts-ignore
  paintOrder: "stroke fill",
  WebkitTextStroke: `1.5px #31124E`,
  textStroke: `1.5px #31124E`,
  textShadow: `
    3px 3px 0px #31124E,
    0px 0px 15px #FFD700
  `,
};

const normalizeRichSource = (value: string): string =>
  value
    .replace(/\r\n?/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\u2028/g, "\n")
    .replace(/\u2029/g, "\n")
    .trim();

const RichText: React.FC<{richText?: string; fallback?: string}> = ({richText, fallback}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

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

  return (
    <>
      {source.split("\n").map((line, lineIndex) => (
        <div key={`line-${lineIndex}`} style={lineStyle}>
          {line.split(/(\*\*[^*]+\*\*)/g).map((chunk, chunkIndex) => {
            if (/^\*\*[^*]+\*\*$/.test(chunk)) {
              const content = chunk.slice(2, -2);

              // Combined entry and perpetual animation
              const entryDuration = 30;
              const delay = lineIndex * 5 + chunkIndex * 2;
              const frameAfterDelay = frame - delay;

              const entryProgress = spring({
                frame: frameAfterDelay,
                fps,
                durationInFrames: entryDuration,
              });

              const initialRotate = interpolate(entryProgress, [0, 1], [-8, -1]);
              const initialScale = interpolate(entryProgress, [0, 1], [0.8, 1]);

              const perpetualFrame = Math.max(0, frameAfterDelay - 15);
              const perpetualScale = 1 + Math.sin(perpetualFrame / 20) * 0.03;
              const perpetualRotate = Math.cos(perpetualFrame / 25) * 1.5;

              const scale = initialScale * perpetualScale;
              const rotate = initialRotate + perpetualRotate;

              return (
                <span
                  key={`highlight-${lineIndex}-${chunkIndex}`}
                  style={{
                    ...highlightStyle,
                    transform: `scale(${scale}) rotate(${rotate}deg)`,
                  }}
                >
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
      ))}
    </>
  );
};

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
  sourceVideoTitle,
  sourceAspect = 16 / 9,
  reactionTimeline = [],
  subtitleTimeline = [],
}) => {
  const {width: W, height: H} = useVideoConfig();

  const videoHeight = W / sourceAspect;
  const bandH = Math.max(0, Math.round((H - videoHeight) / 2));

  const sourceTitle = (sourceVideoTitle ?? "").trim();
  const baseSourceFont = bandH > 0 ? Math.round(bandH * 0.32) : Math.round(H * 0.018);
  const sourceTitleContainerStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    width: '100%',
    background: 'linear-gradient(to bottom, rgba(0, 0, 0, 0.4), transparent)',
    padding: '12px 24px 24px 24px',
    pointerEvents: 'none',
    zIndex: 4,
    textAlign: 'center',
  };
  const sourceTitleTextStyle: React.CSSProperties = {
    fontFamily: textBase.fontFamily,
    fontWeight: 700,
    fontSize: `28px`,
    color: '#FFFFFF',
    letterSpacing: 0.4,
    lineHeight: 1.18,
    textShadow: '0 2px 8px rgba(0,0,0,0.8)',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    width: '100%',
  };

  const topFont = `clamp(28px, ${Math.round(bandH * 0.64)}px, 74px)`;
  const bottomFont = topFont;

  const safePath = videoFileName
    .split("\\")
    .join("/")
    .replace(/^public\//, "");
  const videoSrc = staticFile(safePath);

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
    background: "linear-gradient(135deg, rgba(255, 154, 158, 0.7) 0%, rgba(254, 207, 239, 0.65) 55%, rgba(161, 196, 253, 0.6) 100%)",
    border: "1px solid rgba(255, 255, 255, 0.3)",
    backdropFilter: "blur(18px)",
    margin: "0 auto",
    position: "relative",
    overflow: "hidden",
    animation: 'waver-shadow 7s ease-in-out infinite alternate',
  };

  const topPanelStyle: React.CSSProperties = {
    ...panelBaseStyle,
  };

  const bottomPanelStyle: React.CSSProperties = {
    ...panelBaseStyle,
    padding: "20px 46px",
    borderRadius: 44,
  };

  const topTextStyle: React.CSSProperties = {
    ...textBase,
    fontSize: topFont,
    width: "auto",
    letterSpacing: 1.4,
  };

  const bottomTextStyle: React.CSSProperties = {
    ...textBase,
    fontSize: bottomFont,
    letterSpacing: 1.6,
    textTransform: "none",
    width: "auto",
  };

  return (
    <AbsoluteFill>
      <style>{animationStyles}</style>
      <AnimatedBackground />
      <AbsoluteFill style={{zIndex: 1}}>
        {sourceTitle ? (
          <div style={sourceTitleContainerStyle}>
            <div style={sourceTitleTextStyle}>{sourceTitle}</div>
          </div>
        ) : null}
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
            <div style={{...textBase, fontSize: topFont, width: "auto"}}>
              <RichText richText={topRichText} fallback={topText} />
            </div>
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
            <div style={bottomTextStyle}>
              <RichText richText={bottomRichText} fallback={bottomText} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
