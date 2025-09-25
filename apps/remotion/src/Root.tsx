import {Composition} from 'remotion';
import {VideoWithBands} from './VideoWithBands';
import {z} from 'zod';

const reactionTimelineSchema = z.object({
	startFrame: z.number().int().nonnegative(),
	durationInFrames: z.number().int().positive(),
	text: z.string(),
	emotion: z.string().optional(),
});

// Define the schema for the input props
export const inputPropsSchema = z.object({
	videoFileName: z.string(),
	topText: z.string(),
	bottomText: z.string(),
	topRichText: z.string().optional(),
	bottomRichText: z.string().optional(),
	// The duration is now passed as a prop
	durationInFrames: z.number().positive(),
	reactionTimeline: z.array(reactionTimelineSchema).optional(),
});

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition
				id="VideoWithBands"
				component={VideoWithBands}
				// A dummy duration is required, but it will be overridden by calculateMetadata
				durationInFrames={1}
				fps={30}
				width={1080}
				height={1920}
				schema={inputPropsSchema}
				defaultProps={{
					videoFileName: 'out_clips/clip_001_84-125.mp4',
					topText: 'Default Top Text',
					bottomText: 'Default Bottom Text',
					topRichText: undefined,
					bottomRichText: undefined,
					durationInFrames: 1200, // Default to 40 seconds
					reactionTimeline: [],
				}}
				// Use calculateMetadata to dynamically set the duration from props
				calculateMetadata={async ({props}) => {
					// No async work is needed, but the function must be async.
					// We simply return the duration that was passed in via props.
					return {
						durationInFrames: props.durationInFrames,
					};
				}}
			/>
		</>
	);
};
