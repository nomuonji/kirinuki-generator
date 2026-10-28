"""High-impact offline checks for unattended media stock gating."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packages.quality_gate import (
    candidate_payload, independent_review, select_top_candidates, static_filter, sanitize_candidate_title,
    validated_receipt, verify_rendered_media, write_receipt,
)


def transcript():
    return [
        {"start": 0, "end": 10, "text": "会社を辞めたいです。どうすればいいですか。"},
        {"start": 10, "end": 24, "text": "まず生活費と貯金の額を確認してください。"},
        {"start": 24, "end": 36, "text": "退職前に収入の見通しを作るのが大事です。"},
        {"start": 36, "end": 48, "text": "結論は、生活費を先に計算しましょう。"},
        {"start": 48, "end": 60, "text": "次の話題になります。"},
    ]


def proposal(quote="生活費を先に計算しましょう", start=0, end=48, confidence=0.92):
    return {"start": start, "end": end, "title": "辞める前に考えること",
            "punchline": quote, "reason": "質問への回答と具体例と結論が入っている",
            "confidence": confidence}


class QualityGateTests(unittest.TestCase):
    def test_choose_best_approved_not_just_first_proposal(self):
        # Unapproved high-confidence proposal is removed before this operation.
        c1 = SimpleNamespace(start=100, end=140, confidence=0.81)
        c2 = SimpleNamespace(start=80, end=120, confidence=0.97)
        c3 = SimpleNamespace(start=10, end=45, confidence=0.91)
        chosen = select_top_candidates([c1, c2, c3], 2)
        self.assertEqual([p.start for p in chosen], [10, 80])
        self.assertEqual(select_top_candidates([c1, c2], 0), [c1, c2])

    def test_made_up_quote_cannot_enter_inventory(self):
        passed, audit = static_filter([proposal(quote="辞めるなら今すぐ逃げろ")], transcript())
        self.assertEqual(passed, [])
        self.assertEqual(audit[0]["decision"], "unsupported_punchline")

    def test_strips_only_appended_keyword_dump_before_title_gate(self):
        title = "男性は**金**で人生が変わる？ひろゆきが語る現実の厳しさ [ひろゆき/切り抜き/論破/恋愛/仕事/人生相談/収益化/副業/名言]"
        cleaned, changed = sanitize_candidate_title(title)
        self.assertTrue(changed)
        self.assertEqual(cleaned, "男性は**金**で人生が変わる？ひろゆきが語る現実の厳しさ")

    def test_does_not_rewrite_a_normal_title_with_brackets(self):
        title = "「お金が8割」——ひろゆきの現実論"
        self.assertEqual(sanitize_candidate_title(title), (title, False))

    def test_tagged_title_is_sanitized_but_transcript_gate_still_applies(self):
        good = proposal(quote="生活費を先に計算しましょう")
        good["title"] = "辞める前に考えること [生活費/退職/貯金/転職/キャリア/働き方/相談]"
        passed, audit = static_filter([good], transcript())
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0]["title"], "辞める前に考えること")
        self.assertEqual(audit[0]["decision"], "approved")
        self.assertTrue(audit[0]["titleNormalized"])

        bad = proposal(quote="辞めるなら今すぐ逃げろ")
        bad["title"] = "辞める前に考えること [生活費/退職/貯金/転職/キャリア/働き方/相談]"
        passed_bad, audit_bad = static_filter([bad], transcript())
        self.assertEqual(passed_bad, [])
        self.assertEqual(audit_bad[0]["decision"], "unsupported_punchline")
        self.assertTrue(audit_bad[0]["titleNormalized"])

    def test_overlap_rejection_preserves_high_confidence_candidate(self):
        strong = proposal(confidence=.95)
        weak = proposal(start=8, end=45, confidence=.81)
        passed, audit = static_filter([weak, strong], transcript())
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0]["confidence"], .95)
        self.assertIn("overlapping_or_repetitive", [d["decision"] for d in audit])

    def test_missing_payoff_and_invalid_source_bounds(self):
        passed, audit = static_filter([
            proposal(start=0, end=900),
            proposal(confidence=.4),
        ], transcript())
        self.assertEqual(passed, [])
        self.assertEqual({d["decision"] for d in audit}, {"invalid_boundaries", "weak_model_confidence"})

    def test_valid_receipt_then_tampered_candidate_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            candidates = [proposal()]
            (folder / "clip_candidates.json").write_text(
                json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
            write_receipt(folder, candidates, [{"stage": "review", "approved": True}])
            self.assertTrue(validated_receipt(folder))
            candidates[0]["title"] = "誰も言っていない衝撃発言"
            (folder / "clip_candidates.json").write_text(
                json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
            self.assertFalse(validated_receipt(folder))

    def test_independent_review_rejects_missing_response(self):
        # Import the model SDK in production; here isolate an invalid model
        # response so the no-humans fallback is a hard failure.
        import sys
        import types
        fake_genai = types.ModuleType("google.generativeai")
        fake_genai.configure = lambda **kw: None
        fake_genai.GenerativeModel = lambda name: SimpleNamespace(
            generate_content=lambda *a, **k: SimpleNamespace(text="[]")
        )
        google = types.ModuleType("google")
        google.generativeai = fake_genai
        with patch.dict(sys.modules, {"google": google, "google.generativeai": fake_genai}):
            with patch.dict("os.environ", {"GEMINI_API_KEY": "local-test"}):
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    independent_review([proposal()], transcript())

    def test_media_without_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rendered.mp4"
            path.write_bytes(b"x" * 150000)
            fake_probe = SimpleNamespace(
                stdout=json.dumps({"streams": [
                    {"codec_type": "video", "width": 1080, "height": 1920}
                ], "format": {"duration": "43.2"}})
            )
            with patch("subprocess.run", return_value=fake_probe):
                with self.assertRaisesRegex(RuntimeError, "Media QA failed"):
                    verify_rendered_media(path)

    def test_valid_vertical_video_and_audio_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rendered.mp4"
            path.write_bytes(b"x" * 150000)
            fake_probe = SimpleNamespace(stdout=json.dumps({
                "streams": [
                    {"codec_type": "video", "width": 1080, "height": 1920},
                    {"codec_type": "audio", "channels": 2}
                ],
                "format": {"duration": "43.2"}
            }))
            with patch("subprocess.run", side_effect=[fake_probe, SimpleNamespace()]) as subprocess_mock:
                result = verify_rendered_media(path)
                self.assertEqual(result["audioChannels"], 2)
                self.assertEqual(subprocess_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
