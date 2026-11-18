import copy
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from datetime import datetime, timezone, timedelta
from packages.kyousuki_sources import discover,load_registry,approved_candidates,approved_source,episode_key,catalog_discovery

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


    def test_index_hints_are_untrusted_and_stale_is_not_success(self):
        cfg=copy.deepcopy(BASE)
        row={"bvid":A,"url":f"https://www.bilibili.com/video/{A}/",
             "title":"今天喜欢上你了2026 韩国水原篇 #5","accountHint":"黑田凖一",
             "fetchedAt":NOW.isoformat(),"query":"黑田凖一 韩国水原篇 site:bilibili.com",
             "processingAuthorized":True,"publicationAuthorized":True,"mid":"123"}
        data={"schemaVersion":1,"provider":"brightdata","purpose":"public_metadata_only",
              "writtenAt":NOW.isoformat(),"rows":[row,{**row,"url":"https://evil.example/"}]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"index.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            with patch.dict(os.environ, {"KYOUSUKI_INDEX_FILE":str(path)}):
                def fail(_):
                    self.fail("Configured indexed mode must never fall back to direct API")
                report=discover(cfg,fetch=fail,now=NOW)
                self.assertEqual(report["indexHintCount"],1)
                self.assertEqual(report["status"],"ok")
                self.assertEqual(report["episodeGroups"],{})
                self.assertEqual(report["candidateCount"],0)
                self.assertNotIn("mid",report["indexHints"][0])
                self.assertNotIn("processingAuthorized",report["indexHints"][0])
                self.assertEqual(approved_candidates(report,[],"test-only-folder",NOW,cfg),[])
                cfg["approvedSources"]=[grant(A,"黑田凖一","123")]
                self.assertEqual(len(approved_candidates(report,[],"test-only-folder",NOW,cfg)),1)
                data["rows"]=[{**row,"fetchedAt":(NOW-timedelta(days=4)).isoformat()}]
                path.write_text(json.dumps(data),encoding="utf-8")
                report=discover(cfg,fetch=fail,now=NOW)
                self.assertEqual(report["status"],"degraded")
                self.assertEqual(report["indexHintCount"],0)



    def test_catalog_real_schema_and_denial_stays_metadata_only(self):
        from urllib.error import HTTPError
        cfg=copy.deepcopy(BASE)
        row={"bvid":A,"title":"今天喜欢上你了2026 韩国水原篇 #5",
             "duration":3144,"publish_time":int((NOW-timedelta(days=1)).timestamp()),
             "state":0,"is_ugc_pay":0}
        report=catalog_discovery(cfg,NOW,fetch=lambda mid:([row,{**row,"bvid":B,"is_ugc_pay":1}],5))
        self.assertEqual(report["status"],"ok")
        self.assertEqual(report["candidateCount"],1)
        self.assertEqual(report["latestCatalogCandidate"]["episodeKey"],"2026:スウォン:5")
        self.assertEqual(approved_candidates(report,[],"test-only-folder",NOW,cfg),[])
        cfg["approvedSources"]=[grant(A,"黑田凖一","123")]
        self.assertEqual(len(approved_candidates(report,[],"test-only-folder",NOW,cfg)),1)
        def denied(mid): raise HTTPError("https://uapis.cn",429,"quota",{},None)
        report=catalog_discovery(cfg,NOW,fetch=denied)
        self.assertEqual(report["status"],"degraded")
        self.assertEqual(report["candidateCount"],0)
        self.assertEqual(report["diagnostics"][-1]["httpStatus"],429)

if __name__=="__main__": unittest.main()
