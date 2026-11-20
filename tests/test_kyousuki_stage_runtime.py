"""Preflight staging against a real sidecar path without downloading multi-GB media.

Catches local/global reference errors that compile-only and ASS-only tests miss,
before the expensive 23-clip production render starts.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.kyousuki_rebuild_from_source import stage_clip


class StagingPreflight(unittest.TestCase):
    def test_renders_sidecar_with_original_research_variant_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                work = Path(tmp)
                record = {
                    "episodeKey": "2026:スウォン:2", "index": "001",
                    "sourceBvid": "BV1FNnZ6mEM3",
                    "sourceUploaderMid": "3690992020490662",
                    "startSeconds": 20, "endSeconds": 40,
                    "oldDriveMp4Id": "previous-mp4", "oldDriveJsonId": "previous-json",
                    "data": {
                        "topRichText": "お絵描きで縮まる**距離**",
                        "bottomRichText": "私の**決め手**はあそこ",
                        "variant": 1, "designSeed": 42,
                        "subtitleTimeline": [
                            {"startFrame": 0, "endFrame": 60, "text": "お絵描きしたくて"}
                        ],
                        "reactionTimeline": [],
                        "kirinukiAudit": {
                            "sourceContentId": "BV1FNnZ6mEM3",
                            "sourceVideoUrl": "https://www.bilibili.com/video/BV1FNnZ6mEM3/",
                            "episodeKey": "2026:スウォン:2",
                            "sourceUploaderMid": "3690992020490662",
                        }
                    }
                }
                def render(source, mascot, row, destination, workdir):
                    Path(destination).write_bytes(b"media fixture" * 10000)
                    return {"subtitleCount": 1, "spokenCaptionBottom": 1200, "variant": 0}
                def inspect(file, sidecar, qa_dir, **kwargs):
                    qa_dir.mkdir(parents=True)
                    (qa_dir / "qa.json").write_text('{"status":"pass"}')
                    return {"status": "pass"}
                with (
                    patch("scripts.kyousuki_rebuild_from_source.find_file", return_value=None),
                    patch("scripts.kyousuki_rebuild_from_source.render_episode_cut", side_effect=render),
                    patch("scripts.kyousuki_rebuild_from_source.verify_rendered_media"),
                    patch("scripts.kyousuki_rebuild_from_source.probe", return_value={"format":{"duration":"20.0"}}),
                    patch("scripts.kyousuki_rebuild_from_source.inspect_media", side_effect=inspect),
                    patch("scripts.kyousuki_rebuild_from_source.upload_json_data", return_value="new-json"),
                    patch("scripts.kyousuki_rebuild_from_source.upload_file", return_value="new-mp4"),
                ):
                    result = stage_clip(object(), "review-folder", Path("episode.mp4"),
                                        Path("mascot.png"), record, work)
                self.assertEqual(result["status"], "review_required")
                meta = json.loads((work / "kyousuki_v2_ep2_clip_001.json").read_text())
                self.assertEqual(meta["stockMigration"]["sourceBvid"],record["sourceBvid"])
                self.assertEqual(meta["stockMigration"]["designVersion"],7)
                self.assertEqual(meta["template"],"telop")
                self.assertIn(meta["variant"],(0,1,2))
                self.assertIsInstance(meta["designSeed"],int)
                self.assertEqual(meta["legacyDesignVariant"],1)
                self.assertEqual(meta["topRichText"],record["data"]["topRichText"])
                self.assertEqual(meta["bottomRichText"],record["data"]["bottomRichText"])
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
