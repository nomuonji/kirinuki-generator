# Free JP download probe — 2026-10-20

## Constraints

Cloud-only, no new payment, no credit card registration. No personal account cookies used. Production main, posting, Drive and disabled schedules unchanged.

## Actual tests

Target: `VaUppWRpVeA` (今日好き, 832 seconds, JP-only). Control: `jNQXAC9IVRw` (globally published).

1. Cookie-free Cloudflare watch-page probe: NRT execution observed; both videos returned `LOGIN_REQUIRED`, bot confirmation, zero formats.
2. Set the diagnostic Worker placement to Region / GCP / `asia-northeast1`. This is a Cloudflare placement hint, not creation of any GCP resource. A request from the cloud test environment entered at ORD; a Worker subrequest to Cloudflare trace reported `colo=NRT`. Trace `loc=US` was also observed, so this must not be represented as proof that YouTube classifies the egress IP as Japan.
3. A temporary allowlisted relay forwarded YouTube player/attestation/player-JS and Google attestation requests, stripping account cookies and authorization. No arbitrary origin forwarding, storage or bindings. Media forwarding restricted to bounded byte ranges. Worker expiry: 2026-10-20T08:00:00Z. Diagnostic Worker `kirinuki-jp-probe`, last version `ce3a0add`.
4. Cloud Node.js test used `youtubei.js 17.2.0`, `bgutils-js 3.2.0`, `jsdom 26.1.0`, `canvas 3.2.3`. Retrieved attestation challenge via the relay, executed its interpreter in the temporary cloud runtime, and generated a video-bound PO token. Token length 132, reported integrity-token TTL 43200 seconds. Tokens and raw signed media URLs are not committed.
5. Passed the generated token both to the session and player requests for MWEB, WEB, IOS and ANDROID_VR. All four returned `LOGIN_REQUIRED` / bot confirmation, with zero streaming formats. Report timestamp: 2026-10-20T06:34:45.492Z. No actual video bytes obtained.

| Client with PO token | Result | Formats |
| --- | --- | --- |
| MWEB | LOGIN_REQUIRED | 0 |
| WEB | LOGIN_REQUIRED | 0 |
| IOS | LOGIN_REQUIRED | 0 |
| ANDROID_VR | LOGIN_REQUIRED | 0 |

An earlier direct request from the cloud workspace returned metadata and format entries, but byte requests returned an HTML `Site Unavailable` response. HTTP 200 was not counted as a media success. Early exploratory calls passed a client string to an API expecting an options object; those calls used the default WEB client and are not independent client evidence. Final four-client test used `{client, po_token}` correctly.

## Conclusion and cleanup

The tested cookie-free NRT relay plus generated PO-token path did not restore 今日好き downloading. This does not prove all free methods impossible. PO tokens do not guarantee resolution of IP-based login requirements, as documented by the provider README. Full authenticated-session, alternative trusted-session and residential-egress approaches remain untested; account cookies require explicit handling authorization and must not be exposed in logs or commits. No account session was exported.

The diagnostic Production workers.dev URL was disabled after testing; Preview URLs were already disabled. No custom domains, routes or scheduled triggers were configured. Source probe remains isolated from production. Other two channels' earlier successful full downloads remain documented in PR #34.

References: https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide and https://github.com/Brainicism/bgutil-ytdlp-pot-provider#verification
