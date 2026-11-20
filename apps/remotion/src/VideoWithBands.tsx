import React from "react";
import {AbsoluteFill, staticFile} from "remotion";
import {CleanShort} from "./CleanShort";
import type {ReactionEntry, SubtitleEntry} from "./design/shared";

export type VideoWithBandsProps = {
  videoFileName: string;
  durationInFrames: number;
  sourceAspect?: number;
  reactionTimeline?: ReactionEntry[];
  subtitleTimeline?: SubtitleEntry[];
  /** Optional fallback-only original mascot; requires separate source/frame QA approval. */
  fallbackMascot?: {enabled: boolean; size?: number; right?: number; insetTop?: number};
  /** Legacy metadata accepted to load sidecars; NEVER rendered into frames. */
  topText?: string;
  bottomText?: string;
  topRichText?: string;
  bottomRichText?: string;
  sourceVideoTitle?: string;
  template?: string;
  variant?: number;
  designSeed?: number;
  renderSpecVersion?: number;
};

/** The composition ID stays stable, but every template now uses title-free media layout. */
export const VideoWithBands: React.FC<VideoWithBandsProps> = (props) => {
  const safePath = props.videoFileName.split("\\\\").join("/").replace(/^public\\//, "");
  return (
    <AbsoluteFill lang="ja">
      <CleanShort
        src={staticFile(safePath)}
        aspect={props.sourceAspect && props.sourceAspect > 0 ? props.sourceAspect : 16/9}
        subtitles={props.subtitleTimeline ?? []}
        reactions={props.reactionTimeline ?? []}
        mascot={props.fallbackMascot}
      />
    </AbsoluteFill>
  );
};
