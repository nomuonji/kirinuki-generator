import copy
import unittest
from scripts.kyousuki_upgrade_stock_v6 import EXPECTED, RENDERER, validated_receipts


def fixture():
    return {"schemaVersion":6,"sourceRuns":{"2-3":44761229002,"4-5":44761229001},
      "items":[{"name":name,"sha256":"a"*64,"visualQa":"pass",
                "reviewedBy":"test","screenshots":["beginning.png","middle.png","end.png"],
                "artifactUrl":"https://github.com/nomuonji/kirinuki-generator/actions/runs/1"}
               for name in sorted(EXPECTED)]}


class ReviewedStockUpgradeTests(unittest.TestCase):
    def test_needs_exactly_all_23_reviewed_videos(self):
        self.assertEqual(len(EXPECTED),23)
        self.assertEqual(len(validated_receipts(fixture())),23)
        m=fixture();m["items"].pop()
        with self.assertRaises(ValueError):validated_receipts(m)
    def test_duplicate_unapproved_or_missing_frame_rejected(self):
        m=fixture();m["items"][0]["name"]=m["items"][1]["name"]
        with self.assertRaises(ValueError):validated_receipts(m)
        m=fixture();m["items"][4]["visualQa"]="review_required"
        with self.assertRaises(ValueError):validated_receipts(m)
        m=fixture();m["items"][4]["screenshots"]=["beginning.png","end.png"]
        with self.assertRaises(ValueError):validated_receipts(m)
    def test_wrong_hash_is_rejected(self):
        m=fixture();m["items"][5]["sha256"]="xyz"
        with self.assertRaises(ValueError):validated_receipts(m)
    def test_source_based_v6_renderer(self):
        self.assertIn("v6_researched_telop",RENDERER)


if __name__=="__main__":
    unittest.main()
