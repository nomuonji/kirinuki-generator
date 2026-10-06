import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const videoId = process.argv[2];
const output = process.argv[3];
const quality = process.argv[4] || process.env.SAVETUBE_QUALITY || '720';

if (!videoId || !output) {
  console.error('Usage: node scripts/savetube_download.mjs <video_id> <output_path> [quality]');
  process.exit(2);
}

// SaveTube's public web client decrypts /v2/info responses with this client-side key.
// This is not a credential; if SaveTube changes its client protocol this path will fail
// cleanly and download_video.py will fall back to yt-dlp.
const INFO_KEY = Buffer.from('C5D58EF67A7584E4A29F6C35BBC4EB12', 'hex');
const HEADERS = {
  'content-type': 'application/json',
  origin: 'https://yt.savetube.me',
  referer: 'https://yt.savetube.me/',
  'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36',
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function decryptInfo(payload) {
  const raw = Buffer.from(payload, 'base64');
  if (raw.length <= 16) throw new Error('SaveTube encrypted info payload is too short');
  const iv = raw.subarray(0, 16);
  const encrypted = raw.subarray(16);
  const decipher = crypto.createDecipheriv('aes-128-cbc', INFO_KEY, iv);
  const text = Buffer.concat([decipher.update(encrypted), decipher.final()]).toString('utf8');
  return JSON.parse(text);
}

async function jsonFetch(url, options = {}, timeoutMs = 90000) {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(timeoutMs),
  });
  const text = await response.text();
  console.log('request=', url, 'status=', response.status);
  if (!response.ok) {
    throw new Error(`${url} -> ${response.status}: ${text.slice(0, 400)}`);
  }
  return JSON.parse(text);
}

async function resolveCdn() {
  const endpoints = [
    'https://media.savetube.vip/api/random-cdn',
    'https://media.savetube.me/api/random-cdn',
  ];
  let lastError;
  for (const endpoint of endpoints) {
    try {
      const data = await jsonFetch(endpoint, { headers: HEADERS }, 30000);
      const cdn = data?.cdn || data?.data?.cdn;
      if (cdn) return cdn;
      lastError = new Error(`No CDN in response from ${endpoint}`);
    } catch (error) {
      lastError = error;
      console.error('cdn_resolve_failed=', String(error));
    }
  }
  throw lastError || new Error('No SaveTube CDN endpoint succeeded');
}

async function attemptDownload(attempt) {
  const cdn = await resolveCdn();
  console.log(`attempt=${attempt} cdn=${cdn} quality=${quality}`);

  const infoEnvelope = await jsonFetch(`https://${cdn}/v2/info`, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({ url: `https://www.youtube.com/watch?v=${videoId}` }),
  });

  if (!infoEnvelope?.data) {
    throw new Error(infoEnvelope?.message || 'SaveTube info response had no encrypted data');
  }

  const info = decryptInfo(infoEnvelope.data);
  console.log('title=', info.title || '');
  console.log('duration=', info.duration || '');

  const downloadEnvelope = await jsonFetch(`https://${cdn}/download`, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({
      id: videoId,
      downloadType: 'video',
      quality,
      key: info.key,
    }),
  });

  const downloadUrl = downloadEnvelope?.data?.downloadUrl || downloadEnvelope?.downloadUrl;
  if (!downloadUrl) {
    throw new Error(downloadEnvelope?.message || 'SaveTube download response had no downloadUrl');
  }

  console.log('download_host=', new URL(downloadUrl).host);
  const response = await fetch(downloadUrl, {
    headers: {
      'user-agent': HEADERS['user-agent'],
      referer: 'https://yt.savetube.me/',
    },
    redirect: 'follow',
    signal: AbortSignal.timeout(600000),
  });

  console.log('media_status=', response.status);
  console.log('media_type=', response.headers.get('content-type') || '');
  if (!response.ok || !response.body) {
    throw new Error(`SaveTube media download failed: HTTP ${response.status}`);
  }

  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(output));
  const size = fs.statSync(output).size;
  console.log('downloaded_bytes=', size);
  if (size <= 0) throw new Error('SaveTube wrote an empty file');
}

let lastError;
for (let attempt = 1; attempt <= 4; attempt += 1) {
  try {
    await attemptDownload(attempt);
    process.exit(0);
  } catch (error) {
    lastError = error;
    console.error(`SaveTube attempt ${attempt}/4 failed:`, error?.message || error);
    try {
      if (fs.existsSync(output)) fs.unlinkSync(output);
    } catch {}
    if (attempt < 4) await sleep(1500 * attempt);
  }
}

console.error('All SaveTube attempts failed:', lastError?.stack || lastError);
process.exit(1);
