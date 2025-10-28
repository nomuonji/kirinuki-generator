import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";

export type ReactionTimelineEntry = {
  startFrame: number;
  durationInFrames: number;
  text: string;
  emotion?: string;
};

type ReactionOverlayProps = {
  bottomOffset: number;
  timeline?: ReactionTimelineEntry[];
};

const getMoodColor = (emotion?: string): string => {
  if (!emotion) {
    return "#FF8A65";
  }

  const mood = emotion.toLowerCase();
  if (mood.includes("surprise") || mood.includes("shock") || mood.includes("驚")) {
    return "#FFCA28";
  }
  if (mood.includes("happy") || mood.includes("joy") || mood.includes("嬉") || mood.includes("楽")) {
    return "#4FC3F7";
  }
  if (mood.includes("sad") || mood.includes("涙") || mood.includes("cry")) {
    return "#9575CD";
  }
  if (mood.includes("angry") || mood.includes("怒") || mood.includes("熱")) {
    return "#FF7043";
  }
  return "#81C784";
};

type CharacterAvatarProps = {
  mouthOpen: number;
  tone: string;
};

const CharacterAvatar: React.FC<CharacterAvatarProps> = ({mouthOpen, tone}) => {
  const mouthHeight = 16 + 36 * mouthOpen;

  return (
    <div
      style={{
        position: "relative",
        width: 220,
        height: 260,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          position: "relative",
          width: 200,
          height: 200,
          borderRadius: "50%",
          background: tone,
          boxShadow: "0 18px 34px rgba(0,0,0,0.25)",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 70,
            left: 58,
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "#fff",
            boxShadow: "4px 4px 0 rgba(0,0,0,0.12)",
          }}
        >
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: "#333",
              margin: "6px auto 0",
            }}
          />
        </div>
        <div
          style={{
            position: "absolute",
            top: 70,
            right: 58,
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "#fff",
            boxShadow: "4px 4px 0 rgba(0,0,0,0.12)",
          }}
        >
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: "#333",
              margin: "6px auto 0",
            }}
          />
        </div>
        <div
          style={{
            position: "absolute",
            top: 120,
            left: 45,
            width: 110,
            height: mouthHeight,
            borderRadius: "60%/70%",
            background: "#2E1E0F",
            transition: "height 0.08s ease-out",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: "80%",
              height: "55%",
              borderRadius: "50%",
              background: "#F06292",
            }}
          />
        </div>
        <div
          style={{
            position: "absolute",
            top: 40,
            left: 26,
            width: 148,
            height: 90,
            borderRadius: "50%",
            border: "6px solid rgba(255,255,255,0.55)",
            transform: "rotate(-6deg)",
          }}
        />
      </div>
      <div
        style={{
          width: 96,
          height: 86,
          background: tone,
          borderRadius: "48% 52% 40% 40%",
          marginTop: -36,
          boxShadow: "0 18px 34px rgba(0,0,0,0.25)",
        }}
      />
    </div>
  );
};

const BASE_CONTAINER_HEIGHT = 320;

export const ReactionOverlay: React.FC<ReactionOverlayProps> = ({bottomOffset, timeline = []}) => {
  if (!timeline.length) {
    return null;
  }

  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  const clampedBottom = Math.min(bottomOffset, Math.max(0, height - 120));
  const roomAboveBottom = Math.max(220, height - clampedBottom - 140);
  const scale = Math.min(1.05, Math.max(0.7, roomAboveBottom / (BASE_CONTAINER_HEIGHT + 160)));
  const horizontalPadding = Math.max(32, width * 0.05);
  const overlayWidth = Math.min(420, Math.max(320, width * 0.34));

  const activeReaction = timeline.find(
    (entry) => frame >= entry.startFrame && frame < entry.startFrame + entry.durationInFrames,
  );

  if (!activeReaction) {
    return null;
  }

  const localFrame = frame - activeReaction.startFrame;
  const appear = spring({
    frame: localFrame,
    fps,
    config: {
      damping: 12,
      stiffness: 120,
    },
  });
  const disappearanceWindow = Math.max(12, fps * 0.4);
  const framesRemaining = activeReaction.durationInFrames - localFrame;
  const disappear = Math.min(1, Math.max(0, framesRemaining / disappearanceWindow));
  const visibility = appear * disappear;

  if (visibility <= 0.01) {
    return null;
  }

  const mouthOpenRaw = Math.max(0.1, Math.min(1, 0.1 + 0.9 * Math.abs(Math.sin(localFrame * 0.32))));
  const mouthOpen = mouthOpenRaw * visibility;
  const tone = getMoodColor(activeReaction.emotion);
  const speechLines = activeReaction.text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const translateY = (1 - visibility) * Math.min(28, roomAboveBottom * 0.12);

  return (
    <div
      style={{
        position: "absolute",
        left: horizontalPadding,
        bottom: clampedBottom,
        display: "flex",
        alignItems: "flex-end",
        gap: 24,
        transform: `translateY(${translateY}px) scale(${scale})`,
        transformOrigin: "left bottom",
        opacity: visibility,
        pointerEvents: "none",
        filter: "drop-shadow(0 18px 36px rgba(0,0,0,0.22))",
        zIndex: 6,
      }}
    >
      <CharacterAvatar mouthOpen={mouthOpen} tone={tone} />
      <div style={{position: "relative"}}>
        <div
          style={{
            minWidth: overlayWidth,
            maxWidth: overlayWidth,
            background: "rgba(255,255,255,0.92)",
            borderRadius: 28,
            padding: "22px 28px",
            boxShadow: "0 18px 36px rgba(0,0,0,0.28)",
            color: "#1A1A1A",
            fontFamily: '"M PLUS Rounded 1c", "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif',
            fontWeight: 600,
            fontSize: 32,
            lineHeight: 1.2,
          }}
        >
          {speechLines.length ? (
            speechLines.map((line, idx) => (
              <span key={`line-${idx}`} style={{display: "block"}}>
                {line}
              </span>
            ))
          ) : (
            <span>{activeReaction.text}</span>
          )}
        </div>
        <div
          style={{
            position: "absolute",
            bottom: -28,
            left: 32,
            width: 0,
            height: 0,
            borderLeft: "26px solid transparent",
            borderRight: "26px solid transparent",
            borderTop: "28px solid rgba(255,255,255,0.92)",
            filter: "drop-shadow(0 8px 10px rgba(0,0,0,0.18))",
          }}
        />
      </div>
    </div>
  );
};
