// Only the weights the templates use, so the bundle stays small.
import "@fontsource/noto-sans-jp/800.css";
import "@fontsource/noto-sans-jp/900.css";
import "@fontsource/shippori-mincho-b1/800.css";
import "@fontsource/dela-gothic-one/400.css";
import "@fontsource/dotgothic16/400.css";
import "@fontsource/zen-kaku-gothic-new/500.css";
import "@fontsource/zen-kaku-gothic-new/700.css";
import "@fontsource/zen-kaku-gothic-new/900.css";
import "@fontsource/yusei-magic/400.css";

import {Composition} from "remotion";
import {VideoWithBands} from "./VideoWithBands";
import {z} from "zod";

const reactionTimelineSchema = z.object({
	startFrame: z.number().int().nonnegative(),
	durationInFrames: z.number().int().positive(),
	text: z.string(),
	emotion: z.string().optional(),
});

const subtitleTimelineSchema = z.object({
	startFrame: z.number().int().nonnegative(),
	endFrame: z.number().int().positive(),
	text: z.string(),
});

export const inputPropsSchema = z.object({
	videoFileName: z.string(),
	topText: z.string(),
	bottomText: z.string(),
	topRichText: z.string().optional(),
	bottomRichText: z.string().optional(),
	sourceVideoTitle: z.string().optional(),
	sourceAspect: z.number().positive().optional(),
	durationInFrames: z.number().positive(),
	reactionTimeline: z.array(reactionTimelineSchema).optional(),
	subtitleTimeline: z.array(subtitleTimelineSchema).optional(),
	template: z.string().optional(),
	variant: z.number().int().nonnegative().optional(),
	designSeed: z.number().int().nonnegative().optional(),
});

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition
				id="VideoWithBands"
				component={VideoWithBands}
				// A dummy duration is required, but it is overridden by calculateMetadata.
				durationInFrames={1}
				fps={30}
				width={1080}
				height={1920}
				schema={inputPropsSchema}
				defaultProps={{
					videoFileName: "out_clips/clip_001_84-125.mp4",
					topText: "Default Top Text",
					bottomText: "Default Bottom Text",
					topRichText: undefined,
					bottomRichText: undefined,
					sourceVideoTitle: "Sample Video Title",
					durationInFrames: 1200,
					reactionTimeline: [],
				}}
				calculateMetadata={async ({props}) => ({durationInFrames: props.durationInFrames})}
			/>
		</>
	);
};
