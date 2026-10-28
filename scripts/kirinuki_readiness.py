"""Read-only, redacted production preflight for the direct Kirinuki lane.

Never prints credential values or uploads footage. A successful check does not grant
copyright permission or certify eligibility for YouTube monetization.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BOOL_GATES = ("KIRINUKI_AUTOPUBLISH_ENABLED", "KIRINUKI_SOURCE_RIGHTS_APPROVED",
              "KIRINUKI_CHANNEL_AUTHORIZED")
UPLOAD_SECRETS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
SOURCE_SECRETS = ("YOUTUBE_API_KEY", "OPENCODE_GO_API_KEY")


def preflight(env, *, verify_oauth=False):
    gates = {name: str(env.get(name, "")).strip().lower() == "true" for name in BOOL_GATES}
    oauth_client_present = all(bool(str(env.get(name, "")).strip())
                               for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"))
    refresh_present = bool(str(env.get("YOUTUBE_REFRESH_TOKEN", "")).strip())
    oauth_present = oauth_client_present and refresh_present
    source_present = all(bool(str(env.get(name, "")).strip()) for name in SOURCE_SECRETS)
    has_destination = bool(str(env.get("YOUTUBE_DESTINATION_CHANNEL_ID", "")).strip())
    oauth_result = "missing_credentials_or_destination"
    if verify_oauth and oauth_present and has_destination:
        # Read-only channel lookup validates that token belongs to the intended
        # destination; unlike secrets inventory it makes an actual API request.
        try:
            from packages.youtube_direct import auth_youtube
            auth_youtube()
            oauth_result = "destination_verified"
        except Exception as exc:
            # Do not log exception text: tokens or user-specific material may leak.
            oauth_result = "verification_failed_" + type(exc).__name__
    elif oauth_present and has_destination:
        oauth_result = "not_checked"

    publication_ready = (
        all(gates.values()) and source_present and has_destination
        and oauth_result == "destination_verified"
    )
    blockers = [name for name, enabled in gates.items() if not enabled]
    if not source_present:
        blockers.append("YOUTUBE_API_KEY_or_OPENCODE_GO_API_KEY_missing")
    if not has_destination:
        blockers.append("YOUTUBE_DESTINATION_CHANNEL_ID_missing")
    if not oauth_client_present:
        blockers.append("YOUTUBE_OAUTH_client_id_or_secret_missing")
    if not refresh_present:
        blockers.append("YOUTUBE_OAUTH_refresh_token_missing")
    if oauth_result.startswith("verification_failed"):
        blockers.append("YOUTUBE_OAUTH_channel_mismatch_or_auth_failure")

    return {
        "productionReadyByConfiguration": publication_ready,
        "rightsGateSetByOwner": gates["KIRINUKI_SOURCE_RIGHTS_APPROVED"],
        "rightsAgreementIndependentlyVerified": False,
        "autopublishGateEnabled": gates["KIRINUKI_AUTOPUBLISH_ENABLED"],
        "destinationGateEnabled": gates["KIRINUKI_CHANNEL_AUTHORIZED"],
        "sourceApiAndAiCredentialsPresent": source_present,
        "youtubeDestinationConfigured": has_destination,
        "youtubeOAuthClientPresent": oauth_client_present,
        "youtubeOAuthRefreshTokenPresent": refresh_present,
        "youtubeOAuthCredentialPresent": oauth_present,
        "youtubeOAuthCheck": oauth_result,
        "driveOverflowCredentialsPresent": all(bool(str(env.get(k, "")).strip())
            for k in ("GDRIVE_CLIENT_SECRET_JSON", "GDRIVE_REFRESH_TOKEN")),
        "blockers": blockers,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="readiness.json")
    parser.add_argument("--verify-oauth", action="store_true")
    args = parser.parse_args()
    result = preflight(os.environ, verify_oauth=args.verify_oauth)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
