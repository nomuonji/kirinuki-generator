# Autonomous Kirinuki — production contract (2026-10-21)

## Human-free operation
The owner does not review source videos, choose highlights, edit scripts or inspect rendered clips. The system must choose a source, select clips, reject low-quality clips and render without a human. Automated production is NOT proof of permission or monetization eligibility.

## What this PR enables
- main-tertiary.yml checks Hiroyuki official channel twice daily (00:37 and 12:37 UTC). The lightweight plan job exits unless stock is low and an eligible source exists.
- Secondary Hiroyuki Questions stays manual-only because the recent source pool is sparse. The primary Japan-only source is unchanged and remains blocked.
- Hiroyuki sources use configs/video_concept_hiroyuki.md without manual prompting.
- Deterministic QA rejects unsupported quotes, bad timestamps, weak confidence and duplicate moments.
- An independent Gemini review rejects incoherent clips, misleading titles, missing payoff and abrupt endings. Unavailable reviews fail closed.
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