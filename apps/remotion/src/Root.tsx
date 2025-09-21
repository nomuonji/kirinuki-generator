import {Composition} from 'remotion';
import {VideoWithBands} from './VideoWithBands';
import {z} from 'zod';

// Define the schema for the input props
export const inputPropsSchema = z.object({
	videoFileName: z.string(),
	topText: z.string(),
	bottomText: z.string(),
	// The duration is now passed as a prop
	durationInFrames: z.number().positive(),
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
					durationInFrames: 1200, // Default to 40 seconds
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