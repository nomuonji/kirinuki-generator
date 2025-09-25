import React from "react";
import {AbsoluteFill, Video, staticFile, useVideoConfig} from "remotion";

type VideoWithBandsProps = {
  videoFileName: string;
  topText: string;
  bottomText: string;
  topRichText?: string;
  bottomRichText?: string;
  /** e.g. 16/9, 4/3. Defaults to 16/9 when omitted. */
  sourceAspect?: number;
};

const textBase: React.CSSProperties = {
  fontFamily: "Impact, Arial Black, sans-serif",
  color: "white",
  fontWeight: "bold",
  textAlign: "center",
  textShadow: "0 0 24px rgba(0,0,0,0.95)",
  lineHeight: 1.08,
  width: "100%",
  wordBreak: "break-word",
  whiteSpace: "normal",
  letterSpacing: 0.3,
  paddingLeft: 60,
  paddingRight: 60,
};

const highlightStyle: React.CSSProperties = {
  color: "#FFE066",
  fontSize: "1.16em",
  textShadow: "0 0 28px rgba(0,0,0,0.9)",
};

const renderRichText = (richText?: string, fallback?: string): React.ReactNode => {
  const source = (richText && richText.trim()) || (fallback && fallback.trim());
  if (!source) {
    return "";
  }

  return source.split(/\r?\n/).map((line, lineIndex) => (
    <span key={`line-${lineIndex}`} style={{display: "block"}}>
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
          <span key={`text-${lineIndex}-${chunkIndex}`} style={{display: "inline"}}>
            {chunk}
          </span>
        );
      })}
    </span>
  ));
};

export const VideoWithBands: React.FC<VideoWithBandsProps> = ({
  videoFileName,
  topText,
  bottomText,
  topRichText,
  bottomRichText,
  sourceAspect = 16 / 9,
}) => {
  const {width: W, height: H} = useVideoConfig();

  // Height of the video when scaled using object-fit "contain"
  // For a 9:16 canvas with a 16:9 source: videoHeight = W / sourceAspect
  const videoHeight = W / sourceAspect;

  // Height of the resulting top/bottom letterbox bands
  const bandH = Math.max(0, Math.round((H - videoHeight) / 2));

  // Scale text size relative to band height
  const topFont = `clamp(22px, ${Math.round(bandH * 0.48)}px, 64px)`;
  const bottomFont = `clamp(22px, ${Math.round(bandH * 0.44)}px, 58px)`;

  const safePath = videoFileName
    .split("\\")
    .join("/")
    .replace(/^public\//, "");
  const videoSrc = staticFile(safePath);

  const topContent = renderRichText(topRichText, topText);
  const bottomContent = renderRichText(bottomRichText, bottomText);

  return (
    <AbsoluteFill style={{backgroundColor: "black"}}>
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
        <div style={{...textBase, fontSize: topFont}}>{topContent}</div>
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
        <Video src={videoSrc} style={{width: "100%", height: "100%", objectFit: "contain"}} />
      </div>

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
        <div style={{...textBase, fontSize: bottomFont}}>{bottomContent}</div>
      </div>
    </AbsoluteFill>
  );
};
