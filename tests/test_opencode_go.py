import os
import unittest
from unittest.mock import patch

from packages.opencode_go import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenCodeGoAPIError,
    generate_chat_completion,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {
            "choices": [{"message": {"role": "assistant", "content": "{\"ok\":true}"}}]
        }
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class OpenCodeGoTests(unittest.TestCase):
    def test_openai_compatible_payload_and_bearer_auth(self):
        response = FakeResponse()
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=response) as post:
                result = generate_chat_completion(
                    None,
                    ["You output JSON.", "Return one object."],
                    generation_config={"temperature": 0.2, "response_schema": {"ignored": True}},
                    sleep=lambda _: None,
                    notify=lambda _: None,
                )

        args, kwargs = post.call_args
        self.assertEqual(args[0], DEFAULT_BASE_URL)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["model"], DEFAULT_MODEL)
        self.assertEqual(kwargs["json"]["temperature"], 0.2)
        self.assertEqual(kwargs["json"]["messages"][0]["role"], "system")
        self.assertIn("Return one object.", kwargs["json"]["messages"][1]["content"])
        self.assertNotIn("response_schema", kwargs["json"])
        self.assertEqual(result.text, "{\"ok\":true}")

    def test_legacy_gemini_model_name_never_calls_gemini(self):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                result = generate_chat_completion(
                    "gemini-3.6-flash", ["prompt"], sleep=lambda _: None, notify=lambda _: None
                )
        self.assertEqual(result.model, DEFAULT_MODEL)
        self.assertEqual(post.call_args.kwargs["json"]["model"], DEFAULT_MODEL)

    def test_retries_transient_http_status(self):
        responses = [FakeResponse(status_code=503, text="high demand"), FakeResponse()]
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", side_effect=responses) as post:
                result = generate_chat_completion(
                    DEFAULT_MODEL, "prompt", attempts=2, sleep=lambda _: None, notify=lambda _: None
                )
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result.text, "{\"ok\":true}")

    def test_does_not_retry_authentication_failure(self):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse(
                status_code=401, text="unauthorized"
            )) as post:
                with self.assertRaisesRegex(OpenCodeGoAPIError, "HTTP 401"):
                    generate_chat_completion(
                        DEFAULT_MODEL, "prompt", attempts=3, sleep=lambda _: None, notify=lambda _: None
                    )
        self.assertEqual(post.call_count, 1)

    def test_requires_key_before_network_call(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("packages.opencode_go.requests.post") as post:
                with self.assertRaisesRegex(RuntimeError, "OPENCODE_GO_API_KEY"):
                    generate_chat_completion(DEFAULT_MODEL, "prompt")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
