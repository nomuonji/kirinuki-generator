import os
import unittest
from unittest.mock import patch

from packages.opencode_go import generate_chat_completion
from packages.gemini_api import GeminiAPIError


class Response:
    status_code = 200
    def __init__(self, status=200, text='{"clips": []}'):
        self.status_code = status
        self._text = text
    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}, "finishReason": "STOP"}]}


class GeminiProviderTests(unittest.TestCase):
    def test_auto_chooses_gemini_without_opencode_subscription(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
        }, clear=True):
            with patch("packages.gemini_api.requests.post", return_value=Response()) as post:
                result = generate_chat_completion(
                    "deepseek-v4.1-flash", ["Act as editor", "Transcript excerpt"],
                    generation_config={"temperature": .2}, sleep=lambda n: None,
                )
        self.assertEqual(result.model, "gemini-3.8-flash")
        self.assertEqual(result.text, '{"clips": []}')
        url = post.call_args.args[0]
        self.assertIn("/gemini-3.8-flash:generateContent", url)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Act as editor")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Transcript excerpt")
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertNotIn("test-gemini-key", url)

    def test_explicit_gemini_requires_its_own_key(self):
        with patch.dict(os.environ, {
            "KIRINUKI_AI_PROVIDER": "gemini",
            "OPENCODE_GO_API_KEY": "legacy-key",
        }, clear=True):
            with patch("packages.gemini_api.requests.post") as post:
                with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                    generate_chat_completion(None, "Transcript")
        post.assert_not_called()

    def test_forced_opencode_still_supported(self):
        with patch.dict(os.environ, {
            "KIRINUKI_AI_PROVIDER": "opencode_go",
            "OPENCODE_GO_API_KEY": "legacy-key", "GEMINI_API_KEY": "gemini-key",
        }, clear=True):
            with patch("packages.opencode_go.requests.post") as post:
                post.return_value.status_code = 200
                post.return_value.json.return_value = {
                    "choices": [{"message": {"content": '{"ok":true}'}}]
                }
                result = generate_chat_completion(None, "text")
        self.assertEqual(result.model, "deepseek-v4.1-flash")
        self.assertIn("opencode.ai", post.call_args.args[0])

    def test_gemini_http_failure_does_not_silently_publish(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("packages.gemini_api.requests.post", return_value=Response(status=403)):
                with self.assertRaisesRegex(GeminiAPIError, "HTTP 403"):
                    generate_chat_completion(None, "transcript", attempts=1)
                
    def test_bounded_gemini_retry_for_transient_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("packages.gemini_api.requests.post",
                       side_effect=[Response(status=503), Response()]) as post:
                result = generate_chat_completion(None, "transcript", attempts=2, sleep=lambda n: None, notify=lambda m: None)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result.text, '{"clips": []}')


if __name__ == "__main__":
    unittest.main()
