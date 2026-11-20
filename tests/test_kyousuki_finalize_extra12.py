import unittest
from scripts.kyousuki_finalize_extra12 import EXTRA,INITIAL
from scripts.kyousuki_finalize_v4 import parse_review

def manifest():
    return {"schemaVersion":1,"sourceRunId":44717083325,"items":[
         {"name":name,"sha256":"a"*64,"visualQa":"pass",
          "screenshots":["beginning.png","middle.png","end.png"],
          "reviewedBy":"test","evidenceArtifactUrl":"https://github.com/example/artifact"}
          for name in sorted(EXTRA)]}

class Additional12Contract(unittest.TestCase):
    def test_extra_twelve_separate_from_original_eleven(self):
        self.assertEqual(len(EXTRA),12)
        self.assertEqual(len(INITIAL),11)
        self.assertFalse(EXTRA & INITIAL)
        self.assertEqual(set(parse_review(manifest(),expected=EXTRA)),EXTRA)
    def test_incomplete_additional_stock_is_rejected(self):
        m=manifest()
        m["items"].pop()
        with self.assertRaises(ValueError):
            parse_review(m,expected=EXTRA)
    def test_old_episode_manifest_cannot_approve_new_episode(self):
        m=manifest()
        m["items"][0]["name"]=next(iter(INITIAL))
        with self.assertRaises(ValueError):
            parse_review(m,expected=EXTRA)

if __name__=="__main__":
    unittest.main()
