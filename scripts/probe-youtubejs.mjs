import fs from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import { Innertube } from 'youtubei.js';

const videoId = process.argv[2] || 'jNQXAC9IVRw';
const output = process.argv[3] || 'tmp/youtubejs.mp4';

fs.mkdirSync(new URL('../tmp/', import.meta.url), { recursive: true });

try {
  const youtube = await Innertube.create({
    generate_session_locally: true,
  });

  const info = await youtube.getBasicInfo(videoId);
  console.log('playability=', info.playability_status?.status || 'unknown');
  console.log('title=', info.basic_info?.title || '');

  if (info.playability_status?.status && info.playability_status.status !== 'OK') {
    throw new Error(
      `YouTube.js playability: ${info.playability_status.status} ${info.playability_status.reason || ''}`
    );
  }

  const stream = await youtube.download(videoId, {
    type: 'video+audio',
    quality: 'best',
    format: 'mp4',
  });

  await pipeline(Readable.fromWeb(stream), fs.createWriteStream(output));
  const size = fs.statSync(output).size;
  console.log(`downloaded=${output} bytes=${size}`);
  if (size <= 0) throw new Error('YouTube.js wrote an empty file');
} catch (error) {
  console.error(error?.stack || error);
  process.exit(1);
}
