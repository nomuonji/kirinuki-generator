import React from "react";
import {AbsoluteFill, staticFile, useVideoConfig} from "remotion";
import {TEMPLATES, TEMPLATE_IDS, TemplateId} from "./design/registry";
import {ReactionEntry, SubtitleEntry, hashString, normalizeRich} from "./design/shared";

type VideoWithBandsProps = {
  videoFileName: string;
  topText: string;
  bottomText: string;
  topRichText?: string;
  bottomRichText?: string;
  sourceVideoTitle?: string;
  /** e.g. 16/9, 4/3. Defaults to 16/9 when omitted. */
  sourceAspect?: number;
  durationInFrames: number;
  reactionTimeline?: ReactionEntry[];
  subtitleTimeline?: SubtitleEntry[];
  /** Design template chosen by packages/design_rotation.py. */
  template?: string;
  variant?: number;
  designSeed?: number;
};

/**
 * Entry composition (the id stays "VideoWithBands" so existing render commands keep working).
 * The look is delegated to one of several templates so consecutive uploads don't share a
 * single visual identity; props without a template fall back to a stable hash of the clip.
 */
export const VideoWithBands: React.FC<VideoWithBandsProps> = (props) => {
  const {fps} = useVideoConfig();
  const safePath = props.videoFileName.split("\\").join("/").replace(/^public\//, "");
  const title = normalizeRich(props.topRichText || props.topText || "");
  const punchline = normalizeRich(props.bottomRichText || props.bottomText || "");
  const seed = props.designSeed ?? hashString(`${safePath}|${title}`);

  const requested = props.template as TemplateId | undefined;
  const id: TemplateId = requested && requested in TEMPLATES ? requested : TEMPLATE_IDS[seed % TEMPLATE_IDS.length];
  const {component: Template, variants} = TEMPLATES[id];
  const variant = Math.abs(props.variant ?? Math.floor(seed / 7)) % variants;

  return (
    <AbsoluteFill lang="ja">
    <Template
      videoSrc={staticFile(safePath)}
      title={title}
      punchline={punchline}
      sourceTitle={(props.sourceVideoTitle ?? "").trim()}
      aspect={props.sourceAspect && props.sourceAspect > 0 ? props.sourceAspect : 16 / 9}
      durationInFrames={props.durationInFrames}
      fps={fps}
      subtitles={props.subtitleTimeline ?? []}
      reactions={props.reactionTimeline ?? []}
      variant={variant}
      seed={seed}
    />
    </AbsoluteFill>
  );
};
