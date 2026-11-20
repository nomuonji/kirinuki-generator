import unittest
from scripts.kyousuki_stock_migration import inspect_pair

def fixture():
    bvid="BV1DzW86hE4H"
    stem="kyousuki_v2_ep4_clip_001"
    item={"name":stem+".mp4","size":"4500000"}
    side={"name":stem+".json"}
    data={"renderSpecVersion":2,"videoFileName":stem+".mp4",
          "kirinukiAudit":{"sourceContentId":bvid,"sourceUploaderMid":"3690992020490662",
                           "episodeKey":"2026:スウォン:4"},
          "stockMigration":{"renderSpecVersion":2,"sourceBvid":bvid,
              "sourceUploaderMid":"3690992020490662","episodeKey":"2026:スウォン:4",
              "qaStatus":"pass","mediaIntegrityQa":"pass",
              "oldDriveMp4Id":"old-mp4","oldDriveJsonId":"old-json",
              "newMp4Sha256":"a"*64,"newSizeBytes":4500000}}
    return item,side,data

class MigrationGateTests(unittest.TestCase):
    def test_complete_pair_allowed_when_quality_passes(self):
        v,j,m=fixture()
        self.assertEqual(inspect_pair(v,j,m,{"old-mp4","old-json"}),[])
    def test_no_promotion_when_visual_qa_is_pending(self):
        v,j,m=fixture();m["stockMigration"]["qaStatus"]="review_required"
        self.assertIn("visual_qa_not_passed",inspect_pair(v,j,m,{"old-mp4","old-json"}))
    def test_no_promotion_when_legacy_pair_is_not_archived(self):
        v,j,m=fixture()
        self.assertIn("legacy_pair_not_in_quarantine",inspect_pair(v,j,m,set()))
    def test_cross_episode_mix_rejected(self):
        v,j,m=fixture();m["stockMigration"]["episodeKey"]="2026:スウォン:5"
        self.assertIn("source_episode_mismatch",inspect_pair(v,j,m,{"old-mp4","old-json"}))

if __name__=="__main__":
    unittest.main()
