# Kyousuki automatic source pool

The primary workflow continues the existing four-times-daily stock replenishment.
It reads configs/kyousuki_sources.json every planning run, reports new full-episode
metadata by known account, and groups recognized titles by season and episode.
Account names with unknown MIDs are discovery hints, not verified identities.
The official YouTube lane is unchanged in scope; Hiroyuki and the other lanes do
not use this pool.

Public metadata requests stop on access denial/rate-limiting. They do not log in,
use proxies, or work around access controls. A failed lookup is reported as
degraded, not a successful empty search. Known documented source grants can still
be attempted if discovery is unavailable; unapproved discovery entries are never
media-production candidates.

## Source agreement prerequisite

The account list is **not** a posting allowlist. Keep the repository
approvedSources empty; set the private KYOUSUKI_APPROVALS_JSON Actions secret to a
JSON array only after verifying each actual source's access, processing and
publication rights with the rightsholder and destination owner. Required fields:
bvid, page (positive integer), author, mid (verified numeric ID), episodeKey
(e.g. year:canonical season:episode number), officialEpisodeUrl,
officialPublishedAt (ISO timestamp with timezone), title, durationSeconds,
rightsEvidence (reference to the actual approval, not a claim made by the
uploader), processingAuthorized and publicationAuthorized (both true),
stockFolderId (the explicitly covered existing primary stock folder),
officialYoutubeVideoId when applicable (dedup alias).

The planner uses verified entries in source priority/freshness order after
the normal YouTube candidates. It does not automatically convert public search
hits into approvals. It checks the provider-specific attempt ledger and remote
state, skips completed episodes and avoids switching to a duplicate when any
other provider has generated stock. BBDown verifies the uploader MID during
acquisition, and Japanese captions take precedence. If only Chinese AI captions
exist, exact row alignment is validated before back-translation is accepted.
The rendered output is labeled as a reference translation, not an original quote.
The source adapter selects highest normal available guest format; no high-res
source is promised. Render: 1080x1920, CRF 16, wide full frame, skip redundant
intermediate re-encoding.

Existing editorial/media QA and public-publishing audit flags stay unchanged.
This integrates the existing Drive stock producer, not a new upload channel or
a bypass of the independent public-posting gates. No rights record or posting
credential is manufactured by the planner. Production approval list is empty
as of initial implementation; only public metadata checks and existing YouTube
stock behavior run until valid grants are configured. The translated subtitle
text still requires source-audio verification for reliable verbatim quotation.

## Evidence

Actual privately rendered diagnostic: 
https://github.com/nomuonji/kirinuki-generator/actions/runs/44138101160
(41.66 sec, 1080x1920, two audio channels, complete decode, underlying source 480p).
`kyousuki-source-plan` retains operational metadata for seven days; no footage.

## Public index handoff (metadata only)

The optional KYOUSUKI_INDEX_FILE mode consumes a bounded, fresh snapshot from the repository's kyousuki-index-state branch at state/kyousuki-index.json. The existing primary scheduled workflow checks out that one data file; nothing from the data branch is executed. Missing/stale/empty input is degraded rather than a direct API retry. Identity, upload date, duration, and rights must not be inferred from search snippets; indexHintCount is separate from identity-verified candidateCount. Existing approved-source grants continue to be the sole gate for actual source acquisition. The shared Agent HQ routine can refresh metadata using the existing Keywords Treasury Bright Data quota; the production job needs no new search credential. A fresh index snapshot does not establish permission or prove the target video bytes were retrieved.
