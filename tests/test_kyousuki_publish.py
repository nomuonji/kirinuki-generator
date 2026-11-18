import copy
import unittest
from scripts.kyousuki_publish import publication_item, confirmed_remote
from packages.youtube_direct import source_of

FOLDER="test-only"
GRANT={"bvid":"BV1PwjzzVELc","page":1,"author":"fixture","mid":"123",
       "episodeKey":"2026:fixture:1","officialEpisodeUrl":"https://abema.tv/video/episode/test",
       "rightsEvidence":"synthetic fixture","processingAuthorized":True,"publicationAuthorized":True,
       "stockFolderId":FOLDER}
REG={"accounts":[{"name":"fixture","mid":"123","priority":1}],"approvedSources":[GRANT]}
META={"kirinukiAudit":{"sourcePlatform":"bilibili","sourceContentId":GRANT["bvid"],"sourcePage":1,
       "sourceUploaderMid":"123","episodeKey":GRANT["episodeKey"],"officialEpisodeUrl":GRANT["officialEpisodeUrl"],
       "permissionVerified":True,"transformativeUseVerified":True,"publicPublishingAuthorized":True,
       "publicationSha256":"a"*64,"approvedCandidateDigest":"b"*64,"media":{"sizeBytes":100001},
       "publicationTitle":"fixture clip","publicationDescription":"fixture original commentary"}}

class PublicationTests(unittest.TestCase):
    def test_review_stock_is_not_publication_ready(self):
        item=copy.deepcopy(META)
        for flag in ("permissionVerified","transformativeUseVerified","publicPublishingAuthorized"):
            with self.subTest(flag=flag):
                item=copy.deepcopy(META);item["kirinukiAudit"][flag]=False
                self.assertIsNone(publication_item(item,FOLDER,REG))
        self.assertIsNone(publication_item(META,"wrong-folder",REG))
        self.assertIsNone(publication_item(META,FOLDER,{**REG,"approvedSources":[]}))
        item=copy.deepcopy(META);item["kirinukiAudit"].pop("publicationSha256")
        self.assertIsNone(publication_item(item,FOLDER,REG))
    def test_destination_receipt_requires_actual_marker_and_exact_slot(self):
        item=publication_item(META,FOLDER,REG)
        self.assertIsNotNone(item)
        stamp="2026-11-20T11:00:00Z"
        remote={"snippet":{"description":"KIRINUKI-ID:"+item["fingerprint"]+"\nKIRINUKI-SOURCE:"+item["sourceId"]},
                "status":{"privacyStatus":"private","publishAt":stamp}}
        self.assertEqual(source_of(remote),item["sourceId"])
        self.assertTrue(confirmed_remote(remote,item,stamp))
        self.assertFalse(confirmed_remote(remote,item,"2026-11-21T11:00:00Z"))
        remote["status"]["privacyStatus"]="public"
        self.assertFalse(confirmed_remote(remote,item,stamp))
