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


if __name__ == "__main__":
    unittest.main()
