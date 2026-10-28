# Autonomous Kirinuki — production contract (2026-10-21)

## Human-free operation
The owner does not review source videos, choose highlights, edit scripts or inspect rendered clips. The system must choose a source, select clips, reject low-quality clips and render without a human. Automated production is NOT proof of permission or monetization eligibility.

## What this PR enables
- main-tertiary.yml checks Hiroyuki official channel twice daily (00:37 and 12:37 UTC). The lightweight plan job exits unless stock is low and an eligible source exists.
- Secondary Hiroyuki Questions stays manual-only because the recent source pool is sparse. The primary Japan-only source is unchanged and remains blocked.
- Hiroyuki sources use configs/video_concept_hiroyuki.md without manual prompting.
- Deterministic QA rejects unsupported quotes, bad timestamps, weak confidence and duplicate moments.
- An independent OpenCode Go / DeepSeek V4.1 Flash review rejects incoherent clips, misleading titles, missing payoff and abrupt endings. Unavailable reviews fail closed.
- An approval receipt hashes the exact approved candidate data; Drive manifests preserve it for resume. Unreviewed older clips are regenerated.
- ffprobe and ffmpeg verify vertical dimensions, duration, an audio track and actual decoding before each MP4 upload to Drive.
- No additional paid infrastructure or card registration is required, subject to provider free quotas.

## What this does NOT yet enable
1. This repo saves MP4 and props in Google Drive. It has no YouTube public posting integration, and no proven publisher/readback receipt.
2. No current verification of source creator clipping permissions, MCN revenue sharing or intended YouTube destination authorization. Do not publish before these are established. A creator's participation in an MCN does not itself grant this account rights.
3. Transcript approval and valid MP4 metadata are not enough to prove material is substantially transformative under YouTube reused-content rules. The publication path must independently check for original contextual commentary; captions and reactions alone do not satisfy this.
4. No audience-retention feedback loop is wired to this project. Do not report performance improvement without real YouTube analytics.
5. The owner cannot be replaced by AI for identity checks, legal contracts or YouTube Partner Program application approvals.

## Future publication boundary
Before public upload, the publisher must verify creator permission and source clip restrictions, intended YouTube channel identity via OAuth, matching editorial/media audit, original value-added commentary, and idempotent upload receipt. After posting, persist the returned YouTube ID, privacy status and readback, then collect actual retention metrics.

Fail closed: missing permission, source footage, editorial approval, media decode, API quota or posting credentials must result in no public post, not fabricated completion.

## Direct-to-YouTube lane (Drive only on spillover)

A new workflow, .github/workflows/direct-tertiary.yml, checks at 00:37 and 12:37 UTC. It replaces the scheduled legacy tertiary Drive workflow; the legacy workflow remains available only via manual dispatch. Primary and secondary lanes are unchanged.

The new script (python -m scripts.autonomous_direct) runs as follows:
1. **Fail-closed activation**: require the source-rights confirmation, explicit destination channel authorization, dedicated OAuth refresh credentials and active autopublishing settings. If any are missing, the plan records an inactive status, produces nothing and uploads nothing.
2. **Independent inventory**: read the authenticated YouTube channel's recent uploads/reservations and a dedicated GitHub journal branch kirinuki-state, lanes/hiroyuki-official.json. Journal records are small JSON, never MP4 files.
3. **Bounded publication plan**: default 12:00/20:00 Japan time; one clip per source per day, 14-day reservation window, 14 advance reservations target, maximum 6 uploads per rolling 24 hours as a conservative software guard. This is not a promise of YouTube's actual channel quota.
4. **Production**: acquire the source, transcribe, generate independently approved clips, generate reaction timeline, cut, render and validate video/audio on the GitHub Actions runner. No Drive credential is used on the normal path.
5. **Direct upload**: send a resumable YouTube videos.insert request as private plus publishAt, and save the returned video ID to the GitHub journal. Reading back actual privacy and reservation is required before declaring scheduled.
6. **Spillover**: a confirmed upload limit or full reservation window triggers a Drive upload of just the leftover completed MP4 and small sidecar. On subsequent runs the Drive overflow queue is replayed before generating new clips, and successfully sent fallback files are deleted. Drive is not the primary journal.
7. **Idempotence**: the clip key comes from source ID, start/end and editor version; the YouTube description holds the unique key. Every upload gets a journal receipt before upload begins. Uncertain upload outcomes are reconciled against actual channel uploads. Absence from a limited YouTube listing does NOT authorize automatic retries.

### Activation gates (all required)

GitHub Actions repository **variables**:
- KIRINUKI_AUTOPUBLISH_ENABLED=true (after all checks)
- KIRINUKI_SOURCE_RIGHTS_APPROVED=true (only with actual clipping rights and permission for the destination)
- KIRINUKI_CHANNEL_AUTHORIZED=true (only after validating the intended destination)
- KIRINUKI_DESTINATION_CHANNEL_ID=UC... (actual user-owned publishing channel ID, never the source channel)

GitHub Actions **secrets**:
- YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, YOUTUBE_API_KEY
- OPENCODE_GO_API_KEY, RAPIDAPI_KEY
- GDRIVE_CLIENT_SECRET_JSON and GDRIVE_REFRESH_TOKEN only used by overflow, plus optional YT_COOKIES_TXT

The OAuth refresh token must grant the necessary YouTube scope and belong to the specified destination channel. Google auth consent in Testing may cause refresh credentials to expire. Never copy a token from a different channel or guess authorization.

This configuration intentionally defaults to **inactive**, rather than uploading content without verified creator rights or destination account ownership.

### Remaining real-world verification

The Python unit tests and GitHub Actions CI verify scheduling, gating, data flows and Python syntax; they do not prove actual YouTube OAuth, long-form rendering, publication, creator permission, MCN revenue sharing, or Partner Program monetization. First live authorized run should verify returned video ID, private status, publishAt, quota use, and a spillover/replay with real Drive. If a video is in an uncertain upload state, do not blindly retry.

YouTube official docs: https://developers.google.com/youtube/data/reference/rest/v3/videos/insert and https://developers.google.com/youtube/data/reference/rest/v3/videos

## October 21 Hiroyuki OAuth secret-name mapping and verification

The existing OAuth client IDs for this production lane are stored as
`YT_CLIENT_ID_HIROYUKI` and `YT_CLIENT_SECRET_HIROYUKI`. Workflows now
recognize them without renaming the already-configured secrets.

**OAuth client credentials do not grant channel access.** The separate
`YT_REFRESH_TOKEN_HIROYUKI` refresh-token secret and
`KIRINUKI_DESTINATION_CHANNEL_ID` variable (or Secret) must still be
configured, then a read-only OAuth channel match must succeed. `GDRIVE_REFRESH_TOKEN`
remains Drive-only. See [hiroyuki-youtube-oauth.md](hiroyuki-youtube-oauth.md)
for Google consent and the exact GitHub configuration.

The first private live-source render on 2026-10-21 fetched a full source video
and 52 draft moments; its original smoke setting `--max-clips=1` prematurely
selected one moment which independent editorial review rejected for a truncated
ending. The quality gate correctly failed. Production was changed to review a
larger candidate pool **before** limiting final output, never lowering review
standards. A subsequent private render test is required before treating
end-to-end rendering as proven.
