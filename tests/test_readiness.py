"""Offline test for readiness reports and unauthorized posting safeguards."""
import os
import sys
import types
import unittest
from unittest.mock import patch

from scripts.kirinuki_readiness import preflight


class ReadinessUnitTests(unittest.TestCase):
    def test_missing_authorization_reports_blockers_without_secrets(self):
        env = {
            "YOUTUBE_CLIENT_ID": "private-secret-id",
            "YOUTUBE_CLIENT_SECRET": "private-secret-value",
            "YOUTUBE_REFRESH_TOKEN": "private-refresh-token",
        }
        report = preflight(env)
        self.assertFalse(report["productionReadyByConfiguration"])
        self.assertIn("KIRINUKI_SOURCE_RIGHTS_APPROVED", report["blockers"])
        self.assertNotIn("private-secret-value", str(report))
        self.assertNotIn("private-refresh-token", str(report))

    def test_flags_cannot_replace_oauth_readback(self):
        env = {k: "true" for k in (
            "KIRINUKI_AUTOPUBLISH_ENABLED", "KIRINUKI_SOURCE_RIGHTS_APPROVED",
            "KIRINUKI_CHANNEL_AUTHORIZED")}
        env.update({
            "YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret",
            "YOUTUBE_REFRESH_TOKEN": "refresh",
            "YOUTUBE_DESTINATION_CHANNEL_ID": "UCDESTINATION",
            "YOUTUBE_API_KEY": "yt", "GEMINI_API_KEY": "ai",
        })
        report = preflight(env, verify_oauth=False)
        self.assertEqual(report["youtubeOAuthCheck"], "not_checked")
        self.assertFalse(report["productionReadyByConfiguration"])

        fake = types.ModuleType("packages.youtube_direct")
        fake.auth_youtube = lambda: (object(), "uploads")
        with patch.dict(sys.modules, {"packages.youtube_direct": fake}):
            report = preflight(env, verify_oauth=True)
        self.assertEqual(report["youtubeOAuthCheck"], "destination_verified")
        self.assertTrue(report["productionReadyByConfiguration"])
        self.assertFalse(report["rightsAgreementIndependentlyVerified"])

    def test_oauth_exception_redacts_credentials(self):
        env = {k: "true" for k in (
            "KIRINUKI_AUTOPUBLISH_ENABLED", "KIRINUKI_SOURCE_RIGHTS_APPROVED",
            "KIRINUKI_CHANNEL_AUTHORIZED")}
        env.update({
            "YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "sensitive",
            "YOUTUBE_REFRESH_TOKEN": "refresh",
            "YOUTUBE_DESTINATION_CHANNEL_ID": "UCMISMATCH",
            "YOUTUBE_API_KEY": "yt", "GEMINI_API_KEY": "ai",
        })
        fake = types.ModuleType("packages.youtube_direct")
        def invalid_auth():
            raise RuntimeError("private token secret")
        fake.auth_youtube = invalid_auth
        with patch.dict(sys.modules, {"packages.youtube_direct": fake}):
            result = preflight(env, verify_oauth=True)
        self.assertFalse(result["productionReadyByConfiguration"])
        self.assertEqual(result["youtubeOAuthCheck"], "verification_failed_RuntimeError")
        self.assertNotIn("private token", str(result))
        self.assertNotIn("sensitive", str(result))


if __name__ == "__main__":
    unittest.main()
