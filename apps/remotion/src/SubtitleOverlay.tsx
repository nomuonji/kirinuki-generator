import React from 'react';
import { AbsoluteFill, useCurrentFrame, interpolate } from 'remotion';

// 字幕アイテムの型定義
export type SubtitleEntry = {
  startFrame: number;
  endFrame: number;
  text: string;
};

type SubtitleOverlayProps = {
  timeline: SubtitleEntry[];
};

// テキストスタイル
const subtitleStyle: React.CSSProperties = {
  fontFamily: "'M PLUS Rounded 1c', 'Rounded Mplus 1c', 'Hiragino Maru Gothic ProN', 'Yu Gothic', sans-serif",
  fontWeight: 900,
  fontSize: '42px',
  color: 'white',
  textAlign: 'center',
  lineHeight: 1.3,
  padding: '0 20px',
};

// テキストチャンクのスタイル（背景など）
const textChunkStyle: React.CSSProperties = {
  backgroundColor: 'rgba(0, 0, 0, 0.75)',
  padding: '0.2em 0.4em',
  borderRadius: '0.3em',
  display: 'inline',
  lineHeight: '1.5',
  whiteSpace: 'pre-wrap', // 改行を反映
};

export const SubtitleOverlay: React.FC<SubtitleOverlayProps> = ({ timeline }) => {
  const frame = useCurrentFrame();

  // 現在のフレームに表示すべき字幕を見つける
  const currentSubtitle = timeline.find(
    (subtitle) => frame >= subtitle.startFrame && frame < subtitle.endFrame
  );

  if (!currentSubtitle) {
    return null;
  }

  const start = currentSubtitle.startFrame;
  const end = currentSubtitle.endFrame;
  const duration = end - start;
  const fadeDuration = 5;

  let opacity: number;

  // デュレーションが短すぎて安全にフェードできない場合は、アニメーションをスキップ
  if (duration <= fadeDuration * 2) {
    opacity = 1;
  } else {
    // 通常のフェードアニメーション
    opacity = interpolate(
      frame,
      [start, start + fadeDuration, end - fadeDuration, end],
      [0, 1, 1, 0],
      {extrapolateRight: 'clamp'}
    );
  }

  return (
    <AbsoluteFill
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        // 画面下部に配置
        bottom: '28%',
        top: 'auto',
        height: 'auto',
        opacity: opacity,
      }}
    >
      <div style={subtitleStyle}>
        {currentSubtitle.text.split('\n').map((line, i) => (
          <div key={i} style={{ marginBottom: '0.25em' }}>
            <span style={textChunkStyle}>{line}</span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
