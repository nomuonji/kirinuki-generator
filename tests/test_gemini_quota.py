import unittest
from packages.gemini_quota import quota_delay, with_quota_retry, generate_content_with_fallback


class GeminiQuotaTests(unittest.TestCase):
    def test_parses_real_free_tier_retry_delay(self):
        err = RuntimeError("""429 You exceeded your current quota.
quota_id: "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
retry_delay {
 seconds: 17
}""")
        self.assertEqual(quota_delay(err), 20.0)

    def test_waits_only_for_transient_429(self):
        calls = []
        sleeps = []
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("429 retry_delay { seconds: 17 }")
            return "approved"
        got = with_quota_retry(flaky, attempts=4, sleep=sleeps.append,
                               notify=lambda *args: None)
        self.assertEqual(got, "approved")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [20.0, 20.0])

    def test_does_not_retry_daily_quota(self):
        def daily():
            raise RuntimeError("429 GenerateRequestsPerDayPerProjectPerModel")
        with self.assertRaisesRegex(RuntimeError, "PerDay"):
            with_quota_retry(daily, sleep=lambda _: self.fail("must not sleep"))

    def test_detects_daily_quota_in_structured_details(self):
        class RpcQuotaError(RuntimeError):
            def details(self):
                return 'quota_id: "GenerateRequestsPerDayPerProjectPerModel-FreeTier"'
        with self.assertRaises(RpcQuotaError):
            with_quota_retry(
                lambda: (_ for _ in ()).throw(RpcQuotaError("429 quota exhausted")),
                sleep=lambda _: self.fail("must not sleep"),
            )


    def test_retries_temporary_model_capacity_503(self):
        calls = []
        sleeps = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("503 ServiceUnavailable: This model is currently experiencing high demand.")
            return "render-ready"

        got = with_quota_retry(flaky, attempts=4, sleep=sleeps.append,
                               notify=lambda *args: None)
        self.assertEqual(got, "render-ready")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [15.0, 15.0])

    def test_does_not_retry_unknown_server_failures(self):
        for msg in ["403 permissionDenied", "bad JSON", "502 malformed response"]:
            if msg.startswith("502"):
                # Explicit 5xx responses are transient and should be retried.
                self.assertIsNotNone(quota_delay(RuntimeError(msg)))
                continue
            with self.assertRaises(RuntimeError):
                with_quota_retry(lambda: (_ for _ in ()).throw(RuntimeError(msg)),
                                 sleep=lambda _: self.fail("must not sleep"))

    def test_falls_back_to_alternate_model_on_temporary_503(self):
        requested = []
        notices = []

        class FakeModel:
            def __init__(self, name):
                self.name = name

            def generate_content(self, *args, **kwargs):
                if self.name == "primary-model":
                    raise RuntimeError("503 ServiceUnavailable: high demand")
                return {"model": self.name, "ok": True}

        def factory(name):
            requested.append(name)
            return FakeModel(name)

        got = generate_content_with_fallback(
            "primary-model",
            ["prompt"],
            fallback_models=["backup-model"],
            model_factory=factory,
            attempts=1,
            sleep=lambda _: self.fail("first model must fall back without another retry"),
            notify=notices.append,
        )
        self.assertEqual(got, {"model": "backup-model", "ok": True})
        self.assertEqual(requested, ["primary-model", "backup-model"])
        self.assertEqual(len(notices), 1)

    def test_does_not_retry_bad_auth_or_invalid_json(self):
        for msg in ["403 permissionDenied", "bad JSON"]:
            with self.assertRaisesRegex(RuntimeError, msg):
                with_quota_retry(lambda: (_ for _ in ()).throw(RuntimeError(msg)),
                                 sleep=lambda _: self.fail("must not sleep"))

    def test_stops_after_bounded_retries(self):
        attempts = []
        def exhausted():
            attempts.append(1)
            raise RuntimeError("429 retry_delay { seconds: 15 }")
        with self.assertRaisesRegex(RuntimeError, "429"):
            with_quota_retry(exhausted, attempts=3, sleep=lambda _: None,
                             notify=lambda _: None)
        self.assertEqual(len(attempts), 3)


if __name__ == "__main__":
    unittest.main()
