import fs from 'node:fs';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const videoId = process.argv[2] || 'jNQXAC9IVRw';
const output = process.argv[3] || 'tmp/savetube.mp4';
const quality = process.argv[4] || '720';

const KEY = Buffer.from('C5D58EF67A7584E4A29F6C35BBC4EB12', 'hex');
const HEADERS = {
  'content-type': 'application/json',
  origin: 'https://yt.savetube.me',
  referer: 'https://yt.savetube.me/',
  'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36',
};

function decrypt(payload) {
  const raw = Buffer.from(payload, 'base64');
  const iv = raw.subarray(0, 16);
  const encrypted = raw.subarray(16);
  const decipher = crypto.createDecipheriv('aes-128-cbc', KEY, iv);
  return JSON.parse(Buffer.concat([decipher.update(encrypted), decipher.final()]).toString('utf8'));
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  console.log('request=', url, 'status=', response.status);
  if (!response.ok) throw new Error(`${url} -> ${response.status}: ${text.slice(0, 400)}`);
  return JSON.parse(text);
}

async function resolveCdn() {
  const endpoints = [
    'https://media.savetube.me/api/random-cdn',
    'https://media.savetube.vip/api/random-cdn',
  ];
  let last;
  for (const url of endpoints) {
    try {
      const data = await jsonFetch(url, { headers: HEADERS });
      const cdn = data?.cdn || data?.data?.cdn;
      if (cdn) return cdn;
      last = new Error(`No CDN in response from ${url}`);
    } catch (error) {
      last = error;
      console.error(String(error));
    }
  }
  throw last || new Error('No SaveTube CDN endpoint succeeded');
}

try {
  const cdn = await resolveCdn();
  console.log('cdn=', cdn);

  const infoEnvelope = await jsonFetch(`https://${cdn}/v2/info`, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({ url: `https://www.youtube.com/watch?v=${videoId}` }),
  });
  if (!infoEnvelope?.data) throw new Error('SaveTube info response had no encrypted data');
  const info = decrypt(infoEnvelope.data);
  console.log('title=', info.title || '');
  console.log('duration=', info.duration || '');
  console.log('cached=', info.fromCache ?? '');

  const dlEnvelope = await jsonFetch(`https://${cdn}/download`, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({
      id: videoId,
      downloadType: 'video',
      quality,
      key: info.key,
    }),
  });
  const downloadUrl = dlEnvelope?.data?.downloadUrl || dlEnvelope?.downloadUrl;
  if (!downloadUrl) throw new Error('SaveTube download response had no downloadUrl');
  console.log('download_host=', new URL(downloadUrl).host);

  const response = await fetch(downloadUrl, {
    headers: {
      'user-agent': HEADERS['user-agent'],
      referer: 'https://yt.savetube.me/',
    },
    redirect: 'follow',
  });
  console.log('media_status=', response.status);
  console.log('media_type=', response.headers.get('content-type') || '');
  if (!response.ok || !response.body) {
    throw new Error(`media download failed: ${response.status}`);
  }

  fs.mkdirSync('tmp', { recursive: true });
  await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(output));
  const size = fs.statSync(output).size;
  console.log('downloaded_bytes=', size);
  if (size <= 0) throw new Error('SaveTube wrote an empty file');
} catch (error) {
  console.error(error?.stack || error);
  process.exit(1);
}
