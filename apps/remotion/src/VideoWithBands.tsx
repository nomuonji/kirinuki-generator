import React from "react";
import { AbsoluteFill, Video, staticFile, useVideoConfig } from "remotion";

type VideoWithBandsProps = {
  videoFileName: string;
  topText: string;
  bottomText: string;
  /** 例: 16/9, 4/3。未指定時は 16/9 を仮定 */
  sourceAspect?: number;
};

const textBase: React.CSSProperties = {
  fontFamily: "Impact, Arial Black, sans-serif",
  color: "white",
  fontWeight: "bold",
  textAlign: "center",
  textShadow: "0 0 20px black, 0 0 20px black",
  lineHeight: 1.12,
  width: "100%",
  wordBreak: "break-word",
  whiteSpace: "pre-wrap",
  letterSpacing: 0.2,
  paddingLeft: 60,
  paddingRight: 60,
};

export const VideoWithBands: React.FC<VideoWithBandsProps> = ({
  videoFileName,
  topText,
  bottomText,
  sourceAspect = 16 / 9,
}) => {
  const { width: W, height: H } = useVideoConfig();

  // 画面いっぱいに "contain" で収まったときの動画高さ
  // 9:16 縦長で16:9動画を幅基準で収める: videoHeight = W / sourceAspect
  const videoHeight = W / sourceAspect;

  // 実際にできる上下の黒帯（レターボックス）高さ
  const bandH = Math.max(0, Math.round((H - videoHeight) / 2));

  // テキストサイズは帯の高さから自動算出
  const topFont = `clamp(20px, ${Math.round(bandH * 0.4)}px, 56px)`;
  const bottomFont = `clamp(20px, ${Math.round(bandH * 0.38)}px, 52px)`;

  const safePath = videoFileName
    .split("\\")
    .join("/")
    .replace(/^public\//, "");
  const videoSrc = staticFile(safePath);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* 上帯オーバーレイ（実際の黒帯領域ぴったり） */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: bandH,
          display: "grid",
          placeItems: "center", // ← 縦横ど真ん中
          pointerEvents: "none",
        }}
      >
        <div style={{ ...textBase, fontSize: topFont }}>{topText}</div>
      </div>

      {/* 動画：中央に contain */}
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
        <Video
          src={videoSrc}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>

      {/* 下帯オーバーレイ（実際の黒帯領域ぴったり） */}
      <div
        style={{
          position: "absolute",
          top: H - bandH,
          left: 0,
          right: 0,
          height: bandH,
          transform: "translateY(0)",
          display: "grid",
          placeItems: "center", // ← 縦横ど真ん中
          pointerEvents: "none",
        }}
      >
        <div style={{ ...textBase, fontSize: bottomFont }}>{bottomText}</div>
      </div>
    </AbsoluteFill>
  );
};
