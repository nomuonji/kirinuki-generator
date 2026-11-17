import copy
import unittest
from datetime import datetime, timezone, timedelta
from packages.kyousuki_sources import discover,load_registry,approved_candidates,approved_source,episode_key

NOW=datetime(2026,11,18,0,0,tzinfo=timezone.utc)
BASE={"accounts":[{"name":"黑田凖一","priority":1,"mid":"123"},{"name":"backup","priority":2,"mid":"456"}],"searchKeywords":["today"],"approvedSources":[]}
A="BV1yPJG6oEEN"
B="BV1PwjzzVELc"

def result(bvid,author,mid,title="今天喜欢上你了2026 韩国水原篇 #5"):
    return {"bvid":bvid,"title":title,"author":author,"mid":mid,"duration":"50:00","pubdate":int((NOW-timedelta(days=1)).timestamp())}

def grant(bvid,author,mid):
    return {"bvid":bvid,"page":1,"author":author,"mid":mid,"episodeKey":"2026:スウォン:5",
            "officialYoutubeVideoId":"ABCDEFGHIJK","officialEpisodeUrl":"https://abema.tv/video/episode/90-2056_s830_p5",
            "officialPublishedAt":(NOW-timedelta(days=1)).isoformat(),"durationSeconds":3000,"title":"スウォン編5話",
            "rightsEvidence":"synthetic test fixture only","processingAuthorized":True,
            "publicationAuthorized":True,"stockFolderId":"test-only-folder"}

class SourcePoolTest(unittest.TestCase):
    def test_public_discovery_is_never_approval(self):
        cfg=copy.deepcopy(BASE)
        report=discover(cfg,fetch=lambda kw:[result(A,"黑田凖一","123"),result(B,"backup","456"),result("BV1111111111","blacklisted","789")],now=NOW)
        self.assertEqual(len(report["episodeGroups"]["2026:スウォン:5"]),2)
        self.assertFalse(report["autoAcquisitionAuthorized"])
        self.assertEqual(approved_candidates(report,[],"test-only-folder",NOW,cfg),[])
        with self.assertRaises(ValueError): approved_source(A,1,"test-only-folder",cfg)
    def test_approved_fallback_and_dedupe(self):
        cfg=copy.deepcopy(BASE); cfg["approvedSources"]=[grant(A,"黑田凖一","123"),grant(B,"backup","456")]
        report=discover(cfg,fetch=lambda kw:[],now=NOW)
        rows=approved_candidates(report,[],"test-only-folder",NOW,cfg)
        self.assertEqual([r["bvid"] for r in rows],[A,B])
        failed={"videoId":rows[0]["videoId"],"episodeKey":rows[0]["episodeKey"],"status":"failed","attempts":3}
        self.assertEqual([r["bvid"] for r in approved_candidates(report,[failed],"test-only-folder",NOW,cfg)],[B])
        self.assertEqual(approved_candidates(report,[{**failed,"uploadedClips":1}],"test-only-folder",NOW,cfg),[])
        self.assertEqual(approved_candidates(report,[{"videoId":"ABCDEFGHIJK","status":"completed"}],"test-only-folder",NOW,cfg),[])
        self.assertEqual(approved_candidates(report,[],"wrong-folder",NOW,cfg),[])
    def test_bad_titles_and_identity(self):
        cfg=copy.deepcopy(BASE)
        report=discover(cfg,fetch=lambda kw:[result(A,"黑田凖一","999"),result(B,"backup","456","今日好き2026 水原篇 #5 予告")],now=NOW)
        self.assertEqual(report["candidateCount"],0)
        self.assertIsNone(episode_key("今日好き2026 新しい島編 #1"))
    def test_explicit_grant_must_cover_publication(self):
        cfg=copy.deepcopy(BASE); cfg["approvedSources"]=[{**grant(A,"黑田凖一","123"),"publicationAuthorized":False}]
        with self.assertRaises(ValueError): approved_source(A,1,"test-only-folder",cfg)

if __name__=="__main__": unittest.main()
