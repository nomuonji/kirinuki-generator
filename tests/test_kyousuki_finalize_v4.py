import unittest
from scripts.kyousuki_finalize_v4 import EXPECTED,parse_review

def manifest():
    return {
        "schemaVersion":1,"sourceRunId":44712271039,
        "items":[{"name":name,"sha256":"a"*64,"visualQa":"pass",
                  "screenshots":["beginning.png","middle.png","end.png"],
                  "reviewedBy":"review-fixture","evidenceArtifactUrl":"https://github.com/example/artifact"}
                 for name in sorted(EXPECTED)]
    }

class SourceV4FinalizationTest(unittest.TestCase):
    def test_requires_exact_eleven_frame_reviewed_videos(self):
        self.assertEqual(len(parse_review(manifest())),11)
        d=manifest(); d["items"].pop()
        with self.assertRaises(ValueError): parse_review(d)
    def test_rejects_duplicate_approval_and_nonmatching_hashes(self):
        d=manifest();d["items"][0]["name"]=d["items"][1]["name"]
        with self.assertRaises(ValueError): parse_review(d)
        d=manifest();d["items"][0]["sha256"]="0"*63
        with self.assertRaises(ValueError): parse_review(d)
    def test_rejects_missing_real_frame_evidence(self):
        d=manifest();d["items"][3]["screenshots"]=["middle.png"]
        with self.assertRaises(ValueError): parse_review(d)
        d=manifest();d["items"][3]["visualQa"]="review_required"
        with self.assertRaises(ValueError): parse_review(d)

if __name__=="__main__":
    unittest.main()
