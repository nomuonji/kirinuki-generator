import json
import tempfile
import unittest
from pathlib import Path

from googleapiclient.errors import HttpError
from httplib2 import Response
from packages.youtube_direct import (UploadDeferred, UploadUncertain, fingerprint_of,
                                     reservations, source_of, upload_once)


class FakeRequest:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
    def next_chunk(self, **kwargs):
        if self.error:
            raise self.error
        return None, self.response


class FakeVideos:
    def __init__(self, request):
        self.request = request
        self.body = None
    def insert(self, **kwargs):
        self.body = kwargs["body"]
        return self.request


class FakeYouTube:
    def __init__(self, request):
        self.resource = FakeVideos(request)
    def videos(self):
        return self.resource


def fake_media():
    folder = tempfile.TemporaryDirectory()
    path = Path(folder.name) / "clip.mp4"
    path.write_bytes(b"media-header")
    return folder, path


class YoutubeDirectUnitTests(unittest.TestCase):
    def test_insert_always_private_with_future_publish_at_and_marker(self):
        client = FakeYouTube(FakeRequest({
            "id": "uploaded-v001", "status": {"privacyStatus": "private"}}))
        temp, path = fake_media()
        with temp:
            result = upload_once(
                client, path, title="AI検証済み", description="正確な発言",
                source_video_id="123456789ab", fingerprint="c"*24,
                publish_at="2026-10-25T11:00:00Z")
        body = client.resource.body
        self.assertEqual(result["videoId"], "uploaded-v001")
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(body["status"]["publishAt"], "2026-10-25T11:00:00Z")
        self.assertIn("KIRINUKI-ID:"+"c"*24, body["snippet"]["description"])
        self.assertIn("KIRINUKI-SOURCE:123456789ab", body["snippet"]["description"])

    def test_api_confirms_upload_limit_is_deferred(self):
        error = HttpError(
            Response({"status": 403}),
            json.dumps({"error": {"errors": [{"reason": "uploadLimitExceeded"}]}}).encode())
        client = FakeYouTube(FakeRequest(error=error))
        temp, path = fake_media()
        with temp:
            with self.assertRaises(UploadDeferred):
                upload_once(client, path, title="a", description="b",
                            source_video_id="123456789ab", fingerprint="a"*24,
                            publish_at="2026-10-25T11:00:00Z")

    def test_transport_failure_is_ambiguous_not_blamed_on_quota(self):
        client = FakeYouTube(FakeRequest(error=ConnectionError("socket closed")))
        temp, path = fake_media()
        with temp:
            with self.assertRaises(UploadUncertain):
                upload_once(client, path, title="a", description="b",
                            source_video_id="123456789ab", fingerprint="a"*24,
                            publish_at="2026-10-25T11:00:00Z")

    def test_recover_key_and_future_publish_slot(self):
        video = {
            "id": "video1",
            "snippet": {"description": "KIRINUKI-SOURCE:123456789ab\nKIRINUKI-ID:"+("a"*24)},
            "status": {"privacyStatus": "private", "publishAt": "2026-10-25T11:00:00Z"},
        }
        self.assertEqual(source_of(video), "123456789ab")
        self.assertEqual(fingerprint_of(video), "a"*24)
        self.assertEqual(len(reservations([video])), 1)
        self.assertEqual(reservations([{"status": {"privacyStatus": "public",
                                                  "publishAt": "2026-10-25T11:00:00Z"}}]), [])


if __name__ == "__main__":
    unittest.main()
