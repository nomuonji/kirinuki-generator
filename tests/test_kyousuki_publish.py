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
META={"renderSpecVersion":2,
      "stockMigration":{"qaStatus":"pass","designVersion":5,
                        "rebuildMethod":"source_episode_ffmpeg_v5_wrapped_hook_and_subtitles",
                        "hookText":"視聴者へのフック","captionWrapped":True,"hookWrapped":True},
      "kirinukiAudit":{"sourcePlatform":"bilibili","sourceContentId":GRANT["bvid"],"sourcePage":1,
       "sourceUploaderMid":"123","episodeKey":GRANT["episodeKey"],"officialEpisodeUrl":GRANT["officialEpisodeUrl"],"sourceVideoUrl":"https://www.bilibili.com/video/BV1PwjzzVELc/?p=1",
       "permissionVerified":True,"transformativeUseVerified":True,"publicPublishingAuthorized":True,
       "publicationSha256":"a"*64,"approvedCandidateDigest":"b"*64,"media":{"sizeBytes":100001},
       "publicationTitle":"fixture clip","publicationDescription":"fixture original commentary"}}

class PublicationTests(unittest.TestCase):
    def test_publication_is_independent_of_administrative_rights_flags(self):
        item=copy.deepcopy(META)
        item["kirinukiAudit"]["permissionVerified"]=False
        item["kirinukiAudit"]["transformativeUseVerified"]=False
        item["kirinukiAudit"]["publicPublishingAuthorized"]=False
        self.assertIsNotNone(publication_item(item,FOLDER,REG))
        self.assertIsNotNone(publication_item(item,FOLDER,{**REG,"approvedSources":[]}))
        item=copy.deepcopy(META)
        item["kirinukiAudit"].pop("publicationSha256")
        self.assertIsNone(publication_item(item,FOLDER,REG))
        item=copy.deepcopy(META)
        item["kirinukiAudit"]["sourceUploaderMid"]="999"
        self.assertIsNone(publication_item(item,FOLDER,REG))
    def test_rejects_wrong_design_until_hook_and_caption_upgrade(self):
        old=copy.deepcopy(META)
        old["stockMigration"]["designVersion"]=4
        self.assertIsNone(publication_item(old,FOLDER,REG))
        old=copy.deepcopy(META)
        old["stockMigration"]["hookText"]=""
        self.assertIsNone(publication_item(old,FOLDER,REG))

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
