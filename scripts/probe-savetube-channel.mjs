import fs from 'node:fs';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const apiKey = process.env.YOUTUBE_API_KEY;
const channelId = process.env.YOUTUBE_CHANNEL_ID || 'UCzXVsEc1h2Elljge0fnQYRg';
const output = process.argv[2] || 'tmp/savetube-channel.mp4';
const quality = process.argv[3] || '720';

if (!apiKey) throw new Error('YOUTUBE_API_KEY is required');

const KEY = Buffer.from('C5D58EF67A7584E4A29F6C35BBC4EB12', 'hex');
const HEADERS = {
  'content-type': 'application/json',
  origin: 'https://yt.savetube.me',
  referer: 'https://yt.savetube.me/',
  'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36',
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function decrypt(payload) {
  const raw = Buffer.from(payload, 'base64');
  const iv = raw.subarray(0, 16);
  const encrypted = raw.subarray(16);
  const decipher = crypto.createDecipheriv('aes-128-cbc', KEY, iv);
  return JSON.parse(Buffer.concat([decipher.update(encrypted), decipher.final()]).toString('utf8'));
}

async function textFetch(url, options = {}, timeout = 90000) {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(timeout),
  });
  const text = await response.text();
  console.log('request=', url, 'status=', response.status);
  if (!response.ok) throw new Error(`${url} -> ${response.status}: ${text.slice(0, 500)}`);
  return { response, text };
}

async function jsonFetch(url, options = {}, timeout = 90000) {
  const { text } = await textFetch(url, options, timeout);
  return JSON.parse(text);
}

async function latestVideoCandidates() {
  const url = new URL('https://www.googleapis.com/youtube/v3/search');
  url.searchParams.set('part', 'snippet');
  url.searchParams.set('channelId', channelId);
  url.searchParams.set('type', 'video');
  url.searchParams.set('order', 'date');
  url.searchParams.set('maxResults', '8');
  url.searchParams.set('key', apiKey);
  const data = await jsonFetch(url.toString(), {}, 30000);
  const items = (data.items || [])
    .map((item) => ({
      id: item?.id?.videoId,
      title: item?.snippet?.title || '',
      publishedAt: item?.snippet?.publishedAt || '',
    }))
    .filter((item) => item.id);
  if (!items.length) throw new Error('YouTube Data API returned no recent videos');
  return items;
}

async function resolveCdn() {
  const endpoints = [
    'https://media.savetube.vip/api/random-cdn',
    'https://media.savetube.me/api/random-cdn',
  ];
  let last;
  for (const url of endpoints) {
    try {
      const data = await jsonFetch(url, { headers: HEADERS }, 30000);
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

async function resolveVideo(video) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const cdn = await resolveCdn();
      console.log('candidate=', video.id, 'title=', video.title, 'attempt=', attempt, 'cdn=', cdn);
      const envelope = await jsonFetch(`https://${cdn}/v2/info`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({ url: `https://www.youtube.com/watch?v=${video.id}` }),
      }, 90000);
      if (!envelope?.data) {
        console.log('candidate_info=', JSON.stringify(envelope).slice(0, 1000));
        throw new Error(envelope?.message || 'SaveTube info response had no encrypted data');
      }
      return { cdn, info: decrypt(envelope.data), video };
    } catch (error) {
      lastError = error;
      console.error('candidate_attempt_failed=', video.id, String(error));
      if (attempt < 3) await sleep(1500 * attempt);
    }
  }
  throw lastError || new Error('candidate resolution failed');
}

async function downloadResolved(resolved) {
  const { cdn, info, video } = resolved;
  console.log('selected_video_id=', video.id);
  console.log('selected_title=', info.title || video.title);
  console.log('selected_duration=', info.duration || '');

  const dlEnvelope = await jsonFetch(`https://${cdn}/download`, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({
      id: video.id,
      downloadType: 'video',
      quality,
      key: info.key,
    }),
  }, 90000);
  const downloadUrl = dlEnvelope?.data?.downloadUrl || dlEnvelope?.downloadUrl;
  if (!downloadUrl) {
    console.log('download_response=', JSON.stringify(dlEnvelope).slice(0, 1000));
    throw new Error('SaveTube download response had no downloadUrl');
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
  if (!response.ok || !response.body) throw new Error(`media download failed: ${response.status}`);

  fs.mkdirSync('tmp', { recursive: true });
  await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(output));
  const size = fs.statSync(output).size;
  console.log('downloaded_bytes=', size);
  if (size <= 0) throw new Error('SaveTube wrote an empty file');
}

const candidates = await latestVideoCandidates();
console.log('recent_candidates=', JSON.stringify(candidates));

let selected;
for (const video of candidates) {
  try {
    selected = await resolveVideo(video);
    break;
  } catch (error) {
    console.error('candidate_rejected=', video.id, String(error));
  }
}
if (!selected) throw new Error('No recent channel video could be resolved by SaveTube');
await downloadResolved(selected);
