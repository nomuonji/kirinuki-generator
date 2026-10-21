import unittest
from datetime import datetime, timezone

from packages.publish_scheduler import (eligible_to_post, fingerprint,
                                        reserve_slots, rolling_uploads, JST)


class DirectScheduleTests(unittest.TestCase):
    def test_publish_gates_require_all_approval_and_auth(self):
        self.assertFalse(eligible_to_post({})[0])
        values = {k: "true" for k in (
            "KIRINUKI_DIRECT_MODE", "KIRINUKI_AUTOPUBLISH_ENABLED",
            "KIRINUKI_SOURCE_RIGHTS_APPROVED", "KIRINUKI_CHANNEL_AUTHORIZED"
        )}
        self.assertFalse(eligible_to_post(values)[0])
        values.update({k: "present" for k in (
            "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
            "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_DESTINATION_CHANNEL_ID"
        )})
        self.assertTrue(eligible_to_post(values)[0])
        values["KIRINUKI_SOURCE_RIGHTS_APPROVED"] = "false"
        self.assertFalse(eligible_to_post(values)[0])

    def test_avoid_past_and_same_source_twice_daily(self):
        now = datetime(2026, 10, 21, 6, 30, tzinfo=timezone.utc)  # 15:30 JST
        booked = reserve_slots([], now=now, max_count=3, source_id="abc")
        self.assertEqual(len(booked), 3)
        self.assertEqual(datetime.fromisoformat(booked[0].replace("Z", "+00:00")).astimezone(JST).hour, 20)
        days = [datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(JST).date()
                for x in booked]
        self.assertEqual(len(set(days)), 3)

    def test_another_source_may_take_second_slot(self):
        now = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
        slots = reserve_slots([{"publishAt": "2026-10-21T03:00:00Z",
                                "sourceVideoId": "source_a"}],
                              now=now, max_count=1, source_id="source_b")
        self.assertEqual(slots, ["2026-10-21T11:00:00Z"])

    def test_existing_same_source_pins_next_day(self):
        now = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
        reserved = [{"publishAt": "2026-10-21T03:00:00Z",
                     "sourceVideoId": "x"}]
        found = reserve_slots(reserved, now=now, max_count=1, source_id="x")
        self.assertEqual(found, ["2026-10-22T03:00:00Z"])

    def test_near_future_requires_buffer(self):
        now = datetime(2026, 10, 21, 2, 35, tzinfo=timezone.utc)  # JST 11:35
        found = reserve_slots([], now=now, max_count=1, source_id="x")
        self.assertEqual(found, ["2026-10-21T11:00:00Z"])

    def test_reservation_days_are_bounded(self):
        now = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
        slots = reserve_slots([], now=now, days=2, max_count=50, source_id="x")
        self.assertEqual(len(slots), 2)

    def test_rolling_window(self):
        now = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)
        entries = [
            {"uploadedAt": "2026-10-21T05:00:00Z"},
            {"uploadedAt": "2026-10-20T05:59:59Z"},
            {"uploadedAt": "2026-10-20T06:00:00Z"},
            {"uploadedAt": "not a date"},
        ]
        self.assertEqual(rolling_uploads(entries, now=now), 2)

    def test_fingerprint_is_stable_and_changes_with_timestamp(self):
        self.assertEqual(fingerprint("id", 1.23, 42.34), fingerprint("id", 1.23, 42.34))
        self.assertNotEqual(fingerprint("id", 1.23, 42.34),
                            fingerprint("id", 1.23, 42.35))




class FakeJournal:
    def __init__(self):
        self.data = {"clips": {}, "sources": {}}
    def clip(self, key):
        return self.data["clips"].get(key)
    def set_clip(self, key, **fields):
        record = self.data["clips"].setdefault(key, {})
        record.update(fields)
        return record


class DirectUploadContractTests(unittest.TestCase):
    def setup_lane(self):
        from scripts.autonomous_direct import DirectLane
        lane = DirectLane.__new__(DirectLane)
        lane.ledger = FakeJournal()
        lane.youtube = object()
        lane.actual = []
        lane.provider_slots = []
        lane.max_uploads_per_24h = 6
        lane.uploaded_this_run = 0
        lane.available_capacity = lambda: 4
        lane.next_slot = lambda source: "2026-10-25T11:00:00Z"
        return lane

    def payload(self):
        return {"fingerprint": "a" * 24, "title": "編集済み動画",
                "sourceVideoId": "123456789ab", "description": "独自の解説"}

    def test_scheduled_upload_is_journaled_without_duplicate(self):
        import sys
        import types
        from unittest.mock import patch
        fake = types.ModuleType("packages.youtube_direct")
        fake.UploadDeferred = type("UploadDeferred", (RuntimeError,), {})
        fake.UploadUncertain = type("UploadUncertain", (RuntimeError,), {})
        calls = []
        def upload(*args, **kwargs):
            calls.append(kwargs)
            return {"videoId": "posted-id", "publishAt": kwargs["publish_at"],
                    "uploadedAt": "2026-10-21T06:00:00Z"}
        fake.upload_once = upload
        fake.readback_video = lambda *a: {
            "status": {"privacyStatus": "private",
                       "publishAt": "2026-10-25T11:00:00Z"}
        }
        fake.fingerprint_of = lambda v: None
        lane = self.setup_lane()
        with patch.dict(sys.modules, {"packages.youtube_direct": fake}):
            first = lane.publish(__import__("pathlib").Path("not_used.mp4"), self.payload())
            second = lane.publish(__import__("pathlib").Path("not_used.mp4"), self.payload())
        self.assertEqual(first, "scheduled")
        self.assertEqual(second, "already_handled")
        self.assertEqual(len(calls), 1)
        self.assertEqual(lane.ledger.clip("a" * 24)["videoId"], "posted-id")

    def test_provider_capacity_rejects_and_does_not_retry(self):
        import sys
        import types
        from unittest.mock import patch
        fake = types.ModuleType("packages.youtube_direct")
        fake.UploadDeferred = type("UploadDeferred", (RuntimeError,), {})
        fake.UploadUncertain = type("UploadUncertain", (RuntimeError,), {})
        fake.upload_once = lambda *a, **k: (_ for _ in ()).throw(fake.UploadDeferred("limit"))
        fake.readback_video = lambda *a: None
        fake.fingerprint_of = lambda v: None
        lane = self.setup_lane()
        with patch.dict(sys.modules, {"packages.youtube_direct": fake}):
            disposition = lane.publish(__import__("pathlib").Path("unused.mp4"), self.payload())
        self.assertEqual(disposition, "overflow")
        self.assertEqual(lane.max_uploads_per_24h, 0)
        self.assertEqual(lane.ledger.clip("a" * 24)["status"], "overflow_pending")

    def test_unknown_upload_outcome_is_not_retried(self):
        import sys
        import types
        from unittest.mock import patch
        fake = types.ModuleType("packages.youtube_direct")
        fake.UploadDeferred = type("UploadDeferred", (RuntimeError,), {})
        fake.UploadUncertain = type("UploadUncertain", (RuntimeError,), {})
        fake.upload_once = lambda *a, **k: (_ for _ in ()).throw(fake.UploadUncertain("timeout"))
        fake.readback_video = lambda *a: None
        fake.fingerprint_of = lambda v: None
        lane = self.setup_lane()
        with patch.dict(sys.modules, {"packages.youtube_direct": fake}):
            self.assertEqual(lane.publish(__import__("pathlib").Path("unused.mp4"), self.payload()),
                             "uncertain")
            self.assertEqual(lane.publish(__import__("pathlib").Path("unused.mp4"), self.payload()),
                             "already_handled")
        self.assertEqual(lane.ledger.clip("a" * 24)["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
