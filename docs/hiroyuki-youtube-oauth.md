# Hiroyuki YouTube publishing OAuth setup (one time)

Do not share client secrets, refresh tokens, or auth codes in GitHub Issues,
ChatGPT messages, or workflow logs. Only GitHub Actions repository Secrets.

## What is already configured

The user's existing Hiroyuki OAuth *client credentials* are available under:
- `YT_CLIENT_ID_HIROYUKI`
- `YT_CLIENT_SECRET_HIROYUKI`

The `direct-tertiary.yml` and `kirinuki-readiness.yml` workflows map these
to the Python client's `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`.
Legacy alias names remain supported.

## Still required: offline YouTube refresh token

A client ID and client secret are NOT a YouTube channel authorization.
Google's OAuth requires the owner to consent to the YouTube scope at least once.
Use `https://www.googleapis.com/auth/youtube` with `access_type=offline`
to obtain a refresh token for the *intended posting channel*. Drive's existing
`GDRIVE_REFRESH_TOKEN` is not a substitute.

For a **web application** OAuth client, a one-time browser approach is:
1. Add `https://developers.google.com/oauthplayground` as an authorized
   redirect URI for this OAuth client in Google Cloud Console.
2. In the official [OAuth Playground](https://developers.google.com/oauthplayground/),
   click Settings and enable **Use your own OAuth credentials**, using the
   existing client ID and client secret. Select **Server-side**, **Offline**.
3. Under input-your-own-scopes choose
   `https://www.googleapis.com/auth/youtube`, authorize using the intended
   YouTube channel, and exchange the authorization code for a refresh token.
4. Store the **refresh token only** as GitHub Actions Repository Secret
   `YT_REFRESH_TOKEN_HIROYUKI`. Do not paste it into chat or a PR.
5. Remove the temporary OAuth Playground redirect URI from the client's
   allowed redirects after the token has been obtained (if no other use).

If the existing Google Cloud OAuth client is a **Desktop application**, use
a local loopback / installed-app OAuth authorization flow for that client type,
not the web-app Playground redirect instructions above.

Google OAuth applications left in **Testing** may issue short-lived refresh
tokens; check consent screen publishing/test-user status.

References:
- https://developers.google.com/oauthplayground/
- https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps

## Destination and permission gates

Separately identify the YouTube **destination**, not the original Hiroyuki
source channel. Set repository Variable:
- `KIRINUKI_DESTINATION_CHANNEL_ID=UC...` (or corresponding Secret)

After the destination is confirmed, a read-only readiness workflow verifies
that `channels.list(mine=true)` from the refresh token includes that ID.

Only after confirming the creator's *approval* and applicable conditions,
not merely that an application form was submitted, set repository Variables:
- `KIRINUKI_SOURCE_RIGHTS_APPROVED=true`
- `KIRINUKI_CHANNEL_AUTHORIZED=true`
- `KIRINUKI_AUTOPUBLISH_ENABLED=true`

Until then, the scheduled publish job remains inactive. The separate private
video render smoke test uses no YouTube publishing credentials and does not post.

## Verification

Open **GitHub Actions > Kirinuki Production Readiness** and run it manually.
The report contains booleans only:
- `youtubeOAuthClientPresent`
- `youtubeOAuthRefreshTokenPresent`
- `youtubeDestinationConfigured`
- `youtubeOAuthCheck`

`youtubeOAuthCheck=destination_verified` confirms matching OAuth but does not
prove source clipping rights, transformation, or monetization.
