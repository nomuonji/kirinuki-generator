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
        self.assertTrue(kwargs["headers"]["x-opencode-session"].startswith("ses_"))
        self.assertEqual(kwargs["headers"]["User-Agent"], "kirinuki-generator/1.0")
        self.assertEqual(kwargs["json"]["model"], DEFAULT_MODEL)
        self.assertEqual(kwargs["json"]["reasoning_effort"], "low")
        self.assertEqual(kwargs["json"]["temperature"], 0.2)
        self.assertEqual(kwargs["json"]["messages"][0]["role"], "system")
        self.assertIn("Return one object.", kwargs["json"]["messages"][1]["content"])
        self.assertNotIn("response_schema", kwargs["json"])
        self.assertEqual(result.text, "{\"ok\":true}")

    def test_session_id_is_stable_per_github_attempt(self):
        env = {
            "OPENCODE_GO_API_KEY": "test-key",
            "GITHUB_RUN_ID": "123456",
            "GITHUB_RUN_ATTEMPT": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                generate_chat_completion(DEFAULT_MODEL, "first", sleep=lambda _: None, notify=lambda _: None)
                first = post.call_args.kwargs["headers"]["x-opencode-session"]
                generate_chat_completion(DEFAULT_MODEL, "second", sleep=lambda _: None, notify=lambda _: None)
                second = post.call_args.kwargs["headers"]["x-opencode-session"]
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("ses_"))

    def test_custom_session_id_is_preserved_with_prefix(self):
        with patch.dict(os.environ, {
            "OPENCODE_GO_API_KEY": "test-key",
            "OPENCODE_GO_SESSION_ID": "ses_custom-session",
        }, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                generate_chat_completion(DEFAULT_MODEL, "prompt", sleep=lambda _: None, notify=lambda _: None)
        self.assertEqual(post.call_args.kwargs["headers"]["x-opencode-session"], "ses_custom-session")

    def test_legacy_gemini_model_name_never_calls_gemini(self):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                result = generate_chat_completion(
                    "gemini-3.6-flash", ["prompt"], sleep=lambda _: None, notify=lambda _: None
                )
        self.assertEqual(result.model, DEFAULT_MODEL)
        self.assertEqual(post.call_args.kwargs["json"]["model"], DEFAULT_MODEL)

    def test_reasoning_effort_is_configurable_and_validated(self):
        with patch.dict(os.environ, {
            "OPENCODE_GO_API_KEY": "test-key",
            "OPENCODE_GO_REASONING_EFFORT": "none",
        }, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                generate_chat_completion(DEFAULT_MODEL, "prompt", sleep=lambda _: None, notify=lambda _: None)
        self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "none")

        with patch.dict(os.environ, {
            "OPENCODE_GO_API_KEY": "test-key",
            "OPENCODE_GO_REASONING_EFFORT": "unbounded",
        }, clear=True):
            with patch("packages.opencode_go.requests.post") as post:
                with self.assertRaisesRegex(RuntimeError, "OPENCODE_GO_REASONING_EFFORT"):
                    generate_chat_completion(DEFAULT_MODEL, "prompt")
        post.assert_not_called()

    def test_request_timeout_is_bounded(self):
        with patch.dict(os.environ, {
            "OPENCODE_GO_API_KEY": "test-key",
            "OPENCODE_GO_MAX_TIMEOUT_SECONDS": "90",
        }, clear=True):
            with patch("packages.opencode_go.requests.post", return_value=FakeResponse()) as post:
                generate_chat_completion(
                    DEFAULT_MODEL, "prompt", request_options={"timeout": 600},
                    sleep=lambda _: None, notify=lambda _: None,
                )
        self.assertEqual(post.call_args.kwargs["timeout"], 90)

    def test_retries_transient_http_status(self):
        responses = [FakeResponse(status_code=503, text="high demand"), FakeResponse()]
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", side_effect=responses) as post:
                result = generate_chat_completion(
                    DEFAULT_MODEL, "prompt", attempts=2, sleep=lambda _: None, notify=lambda _: None
                )
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result.text, "{\"ok\":true}")

    def test_retries_empty_content_with_larger_output_budget(self):
        empty_response = FakeResponse(payload={
            "choices": [{
                "message": {"role": "assistant", "content": None, "reasoning_content": "thinking"},
                "finish_reason": "length",
            }]
        })
        responses = [empty_response, FakeResponse()]
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "test-key"}, clear=True):
            with patch("packages.opencode_go.requests.post", side_effect=responses) as post:
                result = generate_chat_completion(
                    DEFAULT_MODEL, "long prompt", attempts=2,
                    sleep=lambda _: None, notify=lambda _: None,
                )
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["max_tokens"], 8192)
        self.assertEqual(post.call_args_list[1].kwargs["json"]["max_tokens"], 16384)
        self.assertEqual(result.text, '{"ok":true}')

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


class SubtitlePolishingTests(unittest.TestCase):
    def test_returns_only_aligned_subtitle_lines_by_clip_index(self):
        from types import SimpleNamespace
        from packages.segmentation_gemini.client import polish_subtitles_bulk

        response = SimpleNamespace(parsed=[
            {"index": 2, "lines": ["こんにちは。", "元気ですか？"]},
            {"index": 1, "lines": ["今日は晴れです。"]},
        ])
        with patch("packages.segmentation_gemini.client.generate_chat_completion", return_value=response) as generate:
            result = polish_subtitles_bulk([
                {"index": 1, "lines": ["今日は晴れです"]},
                {"index": 2, "lines": ["こんにちは", "元気ですか"]},
            ], concept="テスト")

        self.assertEqual(result, {
            1: ["今日は晴れです。"],
            2: ["こんにちは。", "元気ですか？"],
        })
        prompt_messages = generate.call_args.args[1]
        self.assertIn('"index": 1', prompt_messages[2])
        self.assertIn("same number of lines", prompt_messages[0])

    def test_omits_malformed_results_so_callers_keep_original_lines(self):
        from types import SimpleNamespace
        from packages.segmentation_gemini.client import polish_subtitles_bulk

        response = SimpleNamespace(parsed=[
            {"index": 1, "lines": ["修正済み"]},
            {"index": 2, "lines": ["一行だけ"]},  # Original has two lines.
            {"index": 3, "lines": ["", "二行目"]},  # Must not erase a non-empty line.
        ])
        with patch("packages.segmentation_gemini.client.generate_chat_completion", return_value=response):
            result = polish_subtitles_bulk([
                {"index": 1, "lines": ["修正前"]},
                {"index": 2, "lines": ["一行目", "二行目"]},
                {"index": 3, "lines": ["一行目", "二行目"]},
            ])

        self.assertEqual(result, {1: ["修正済み"]})

    def test_empty_inputs_do_not_call_model(self):
        from packages.segmentation_gemini.client import polish_subtitles_bulk

        with patch("packages.segmentation_gemini.client.generate_chat_completion") as generate:
            self.assertEqual(polish_subtitles_bulk([]), {})
        generate.assert_not_called()

    def test_hook_generator_remains_available(self):
        from packages.segmentation_gemini.client import generate_hooks_bulk

        self.assertTrue(callable(generate_hooks_bulk))


if __name__ == "__main__":
    unittest.main()
