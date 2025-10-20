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
Config.setDelayRenderTimeoutInMilliseconds(120000);
