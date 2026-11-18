import unittest
from datetime import datetime, timezone
from scripts.kyousuki_review import select_review, _private_folder, FOLDER_NAME, FOLDER_TYPE
from unittest.mock import MagicMock

NOW=datetime(2026,11,19,0,0,tzinfo=timezone.utc)
REG={"accounts":[{"name":"known","mid":"123","priority":1}],"approvedSources":[]}
ROW={"bvid":"BV1zaJR6BEq2","title":"今天喜欢上你了2026 韩国水原篇 #1",
    "mid":"123","author":"known","publishedAt":"2026-11-18T00:00:00+00:00",
    "durationSeconds":3000,"metadataProvider":"uapipro","identityStatus":"catalog_account_binding",
    "permissionVerified":True,"publicPublishingAuthorized":True}
def plan(row=ROW):
    return {"shouldProcess":False,"blockingReasons":["no_valid_bilibili_source_grants"],
        "bilibiliSourcePool":{"status":"ok","discoveryMode":"public_catalog","checkedAt":NOW.isoformat(),"latestCatalogCandidate":row}}

class ReviewTest(unittest.TestCase):
    def test_unregistered_review_without_asserting_approval(self):
        c=select_review(plan(),REG,NOW)
        self.assertEqual(c["bvid"],ROW["bvid"])
        self.assertNotIn("permissionVerified",c)
        self.assertNotIn("publicPublishingAuthorized",c)
        self.assertIsNone(select_review(plan({**ROW,"mid":"456"}),REG,NOW))
        self.assertIsNone(select_review(plan({**ROW,"metadataProvider":"brightdata"}),REG,NOW))
        p=plan();p["shouldProcess"]=True
        self.assertIsNone(select_review(p,REG,NOW))
    def test_isolation_rejects_shared_or_stock_destination(self):
        s=MagicMock()
        s.files().get().execute.side_effect=[{"name":FOLDER_NAME,"mimeType":FOLDER_TYPE,
            "ownedByMe":True,"parents":["rootid"]},{"id":"rootid"}]
        s.permissions().list().execute.return_value={"permissions":[{"type":"user","role":"owner"},{"type":"anyone","role":"reader"}]}
        with self.assertRaises(ValueError):
            _private_folder(s,"review","stock")
        with self.assertRaises(ValueError):
            _private_folder(s,"stock","stock")

if __name__=="__main__": unittest.main()
