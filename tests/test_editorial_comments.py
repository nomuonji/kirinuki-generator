"""Editorial comments must be sourced to a transcript cue, not imagined viewers."""
import unittest

from apps.cli.generate_reactions import _sanitize_editorial_entries


class EditorialCommentTimingTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"start": 0.2, "duration": 1.4, "text": "最初は友達だと思ってた"},
            {"start": 7.0, "duration": 1.8, "text": "でも昨日から気になってる"},
            {"start": 14.0, "duration": 1.4, "text": "やっぱり好きだった"},
        ]

    def test_cue_is_aligned_to_spoken_line_end_not_shown_before_it(self):
        result = _sanitize_editorial_entries([
            {"triggerText": "友達だと思ってた", "startTimeSec": 1.5,
             "durationSec": 2.1, "text": "ここから変わる？"},
            {"triggerText": "昨日から気になってる", "startTimeSec": 8.7,
             "durationSec": 2.0, "text": "あ、流れが変わった"},
        ], max_reactions=3, clip_duration=20, segments=self.segments)
        self.assertEqual([r["startTimeSec"] for r in result], [1.78, 8.98])
        self.assertTrue(all(r["emotion"] == "editorial" for r in result))

    def test_fabricated_or_badly_timed_cues_cannot_be_rendered(self):
        result = _sanitize_editorial_entries([
            {"triggerText": "存在しない台詞", "startTimeSec": 1.4,
             "durationSec": 2.0, "text": "捏造"},
            {"triggerText": "最初は友達", "startTimeSec": 18,
             "durationSec": 2.0, "text": "時刻が違う"},
            {"triggerText": "好きだった", "startTimeSec": 15.3,
             "durationSec": 2.0, "text": "長すぎるので十九文字以上にしてはいけないです"},
        ], max_reactions=3, clip_duration=20, segments=self.segments)
        self.assertEqual(result, [])

    def test_overlapping_comments_are_suppressed(self):
        result = _sanitize_editorial_entries([
            {"triggerText": "最初は友達", "startTimeSec": 1.5,
             "durationSec": 2.3, "text": "一つ目"},
            {"triggerText": "友達だと思ってた", "startTimeSec": 1.5,
             "durationSec": 2.3, "text": "同じタイミング"},
        ], max_reactions=3, clip_duration=20, segments=self.segments)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
