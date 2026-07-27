import {Config} from '@remotion/cli/config';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// Calculate the absolute path to the public directory
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.resolve(__dirname, 'public');

// Set the public directory with an absolute path to avoid CWD issues
Config.setPublicDir(PUBLIC_DIR);

// Increase log level for better debugging
Config.setLogLevel('verbose');

// If on Windows, force MS Edge for better stability
if (process.platform === 'win32') {
    Config.setChromiumExecutable('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe');
}

// Stabilize rendering on ARM environments by fixing the GL driver
Config.setChromiumOpenGlRenderer?.('swangle');

// Other configurations
Config.setVideoImageFormat('jpeg');
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');

// Remotion defaults to CRF 18 for h264, which produced ~5.2 Mbps / ~50 MB per 80-second
// vertical clip — enough to fill a 15 GB Drive in five videos. The platforms these clips
// are posted to re-encode on upload, so those bits are discarded anyway. CRF 24 lands
// around 1.5-2 Mbps with no visible difference after that re-encode.
// Override with REMOTION_CRF to trade size against quality (higher = smaller).
Config.setCrf(Number(process.env.REMOTION_CRF ?? 24));
// Cap bitrate spikes on high-motion sections so a single clip cannot balloon.
Config.setEncodingMaxRate('3M');
Config.setEncodingBufferSize('6M');
Config.setDelayRenderTimeoutInMilliseconds(180000);
Config.setRenderTimeoutInMilliseconds(180000);
