from datetime import datetime, timedelta, timezone
import unittest

from packages.operations import (
    OperationsConfig,
    clips_needed_for_source,
    estimate_effective_stock,
    rank_source_candidates,
)


class OperationsTests(unittest.TestCase):
    def test_stock_consumes_at_expected_posting_rate(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        entries = [
            {
                "status": "completed",
                "processedAt": (now - timedelta(days=2)).isoformat(),
                "uploadedClips": 10,
            }
        ]
        self.assertAlmostEqual(
            estimate_effective_stock(entries, posts_per_day=2, now=now),
            6.0,
            places=4,
        )

    def test_stock_never_goes_negative_between_batches(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        entries = [
            {
                "status": "completed",
                "processedAt": (now - timedelta(days=10)).isoformat(),
                "uploadedClips": 2,
            },
            {
                "status": "completed",
                "processedAt": (now - timedelta(days=1)).isoformat(),
                "uploadedClips": 5,
            },
        ]
        self.assertAlmostEqual(
            estimate_effective_stock(entries, posts_per_day=2, now=now),
            3.0,
            places=4,
        )

    def test_velocity_can_beat_pure_recency(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        ranked = rank_source_candidates(
            [
                {
                    "videoId": "new",
                    "publishedAt": (now - timedelta(hours=2)).isoformat(),
                    "durationSeconds": 1200,
                    "views": 100,
                    "likes": 2,
                    "comments": 0,
                },
                {
                    "videoId": "hot",
                    "publishedAt": (now - timedelta(hours=12)).isoformat(),
                    "durationSeconds": 1800,
                    "views": 100000,
                    "likes": 5000,
                    "comments": 800,
                },
            ],
            now=now,
        )
        self.assertEqual(ranked[0]["videoId"], "hot")

    def test_clip_request_is_capped_by_source(self):
        self.assertEqual(clips_needed_for_source(2, 14, 6), 6)
        self.assertEqual(clips_needed_for_source(10, 14, 6), 4)
        self.assertEqual(clips_needed_for_source(14, 14, 6), 0)

    def test_default_stock_targets(self):
        config = OperationsConfig()
        self.assertEqual(config.target_stock_clips, 14)
        self.assertEqual(config.reorder_stock_clips, 6)


if __name__ == "__main__":
    unittest.main()
