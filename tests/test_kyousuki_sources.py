import copy
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from datetime import datetime, timezone, timedelta
from packages.kyousuki_sources import account_uploads,discover,load_registry,approved_candidates,approved_source,episode_key

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
    def test_archive_payload_mapping_and_identity(self):
        row=result(A,"黑田凖一","123")
        row["length"]=row.pop("duration"); row["created"]=row.pop("pubdate")
        unrelated={**row,"bvid":B,"title":"other long programme"}
        with patch("packages.kyousuki_sources.public_metadata",return_value={"list":{"vlist":[row, unrelated]}}) as api:
            entries=account_uploads(BASE["accounts"][0])
            self.assertEqual([r["bvid"] for r in entries],[A])
            self.assertEqual(entries[0]["duration"],"50:00")
            self.assertEqual(entries[0]["pubdate"],row["created"])
            self.assertEqual(api.call_args.args[1]["mid"],"123")
            self.assertNotIn("keyword",api.call_args.args[1])
        with patch("packages.kyousuki_sources.public_metadata",return_value={"list":{"vlist":[{**row,"mid":"999"}]}}):
            with self.assertRaises(ValueError): account_uploads(BASE["accounts"][0])

    def test_denial_stops_polling_and_preserves_approved_fallback(self):
        cfg=copy.deepcopy(BASE)
        cfg["approvedSources"]=[grant(A,"黑田凖一","123")]
        calls=[]
        def fetch(account):
            calls.append(account["mid"])
            raise HTTPError("https://api.bilibili.com",412,"denied",{},None)
        report=discover(cfg,fetch=fetch,now=NOW)
        self.assertEqual(calls,["123"])
        self.assertEqual(report["status"],"degraded")
        self.assertEqual(report["diagnostics"][1]["status"],"not_attempted_after_denial")
        self.assertEqual(len(approved_candidates(report,[],"test-only-folder",NOW,cfg)),1)

    def test_unknown_mid_resolves_exact_marked_account(self):
        cfg=copy.deepcopy(BASE)
        cfg["accounts"][0]["mid"]=None
        calls=[]
        def fetch(account):
            calls.append(account["mid"])
            return [result(A,"黑田凖一","123")]
        report=discover(cfg,fetch=fetch,now=NOW,resolve=lambda account:"123")
        self.assertEqual(calls,["456","123"])
        self.assertEqual(report["candidateCount"],1)
        self.assertFalse(report["autoAcquisitionAuthorized"])

    def test_explicit_grant_must_cover_publication(self):
        cfg=copy.deepcopy(BASE); cfg["approvedSources"]=[{**grant(A,"黑田凖一","123"),"publicationAuthorized":False}]
        with self.assertRaises(ValueError): approved_source(A,1,"test-only-folder",cfg)

if __name__=="__main__": unittest.main()
