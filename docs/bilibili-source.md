# Bilibili input adapter (opt-in)

BBDown 1.6.3 is pinned: GitHub Actions verified actual MP4 acquisition (video + audio)
and actual SRT extraction on separate openly licensed samples. The live adapter
smoke checks both files from the same part. Bilibili is not a replacement for
the existing YouTube lane by default.

## Usage

For a specific source for which access, downloading and processing of the video
and subtitles are authorized:

```bash
dotnet tool install --global BBDown --version 1.6.3
# Install ffmpeg/ffprobe and ensure BBDown is on PATH.
python bilibili_source.py video YOUR_BV_ID --page 1 --rights-confirmed --output tmp/video.mp4
python bilibili_source.py transcript YOUR_BV_ID --page 1 --language ja --rights-confirmed --video tmp/video.mp4 --output tmp/transcript.json
```

The output contract is unchanged: video.mp4 and an array of
{start, end, duration, text}. BBDown's return code is not sufficient: actual
files, both media streams, positive duration and valid timestamped cues are
mandatory. There is no cross-language implicit fallback. Choose ja, zh, or en
explicitly. Within the requested language, human/regular CC is preferred to
AI captions where both exist. A translated Chinese caption is not the original
Japanese dialogue; do not burn it in as though it were.

For the entire existing generator, use the manual Actions workflow
**Manual authorized Bilibili clip generation** with an explicitly isolated
`BILIBILI_REVIEW_FOLDER_ID` repository secret (different from any scheduled
or automatic-publishing stock folder), the BV identifier, part, language and
source authorization confirmation. Existing Google Drive and OpenCode secrets
are used. Non-Japanese captions are used for scene analysis without subtitle
burn-in. Equivalent local invocation:

```bash
# Both folder variables must point to the same dedicated review-only folder.
python run_all.py YOUR_BV_ID --source-platform bilibili --bilibili-page 1 --bilibili-subtitle-lang ja --source-rights-confirmed --subs
```

The per-part/per-language state key is namespaced and clip audit identifies
Bilibili, not YouTube. Source authorization confirmation is not a verified
publishing approval: existing public publishing flags stay false. There is
no change to YouTube source discovery, cron, or direct posting. No automatic
search for reuploads, attempts to bypass access denials, or credential exports.

If no subtitle track is available the pipeline fails closed, not with a
fabricated transcript. The availability of subtitles for the specific target
episode and permission for the chosen source still need to be established.

Evidence:
- CC BY media probe: https://github.com/nomuonji/kirinuki-generator/actions/runs/44118831521/job/134164261797
- Subtitle extraction probe (noncommercial CS50 sample): https://github.com/nomuonji/kirinuki-generator/actions/runs/44124466481/job/134184351961
- Bilibili target episode metadata only: https://github.com/nomuonji/kirinuki-generator/actions/runs/44119301730/job/134165931941
