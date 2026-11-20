import json
import tempfile
import unittest
from pathlib import Path

from packages.kyousuki_researched_telop import (
    VARIANTS, ass_color, break_rich, render_ass, spoken_caption, telop_variant
)

class ResearchBasedTelopTests(unittest.TestCase):
    def test_hook_and_punchline_are_both_rendered_but_source_title_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"telop.ass"
            result=render_ass(
                subtitles=[
                    {"startFrame":0,"endFrame":90,"text":"お絵描き、好きって言ったじゃん。"},
                    {"startFrame":91,"endFrame":180,"text":"ちょっと、絵もいいよ。適当。適当でっていうか、伝わるなら。"}],
                seconds=7,output=path,video_top=566,video_height=608,
                hook="お絵描きで縮まる**距離**",
                punchline="私の**決め手**はあそこ",variant=0)
            text=path.read_text(encoding="utf-8")
            self.assertEqual(result["subtitleCount"],2)
            self.assertEqual(result["template"],"telop")
            self.assertEqual(result["deadSpaceTreatment"],"dark_source_blur")
            self.assertEqual(result["spokenCaptionBottom"],1154)
            self.assertIn("お絵描きで縮まる",text)
            self.assertIn("距離",text)
            self.assertIn("私の",text)
            self.assertIn("決め手",text)
            self.assertIn("Dialogue: 0",text)
            self.assertIn("Dialogue: 1",text)
            self.assertNotIn("sourceVideoTitle",text)
            self.assertNotIn("今天喜欢上你了",text)
            self.assertIn(r"\N",text)
            self.assertIn(ass_color(VARIANTS[0]["hl"][0]),text)

    def test_long_hook_and_all_three_variants_fit_safe_bounds(self):
        for variant in range(3):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                result=render_ass(subtitles=[
                    {"startFrame":0,"endFrame":40,"text":"話してくれてありがとう"}],
                    seconds=3,output=Path(temp)/"out.ass",video_top=566,video_height=608,
                    hook="気持ちを伝えてくれてるから…**付き合いたい**って思ってる",
                    punchline="**付き合いたい**って思ってる",variant=variant)
                self.assertEqual(result["variant"],variant)
                self.assertLessEqual(result["hookRows"],2)
                self.assertLessEqual(result["punchRows"],2)

    def test_legacy_uniform_palette_is_replaced_with_full_three_variant_cycle(self):
        sequence=[]
        for ep,qty in ((2,6),(3,6),(4,5),(5,6)):
            for idx in range(1,qty+1):
                sequence.append(telop_variant(f"2026:スウォン:{ep}",idx))
        self.assertEqual(len(sequence),23)
        self.assertEqual(set(sequence),{0,1,2})
        self.assertTrue(all(a!=b for a,b in zip(sequence,sequence[1:])))

    def test_long_subtitle_wraps_without_dropping_any_character(self):
        line="ちょっと、絵もいいよ。適当。適当でっていうか、伝わるなら。"
        wrapped=spoken_caption(line)
        after=wrapped.split("}",1)[1].replace(r"\N","")
        self.assertEqual(after,line)

    def test_rejects_missing_editorial_punch_and_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            base=dict(subtitles=[{"startFrame":0,"endFrame":30,"text":"うん"}],
                    seconds=2,output=Path(temp)/"x.ass",
                    video_top=566,video_height=608,variant=0)
            with self.assertRaises(ValueError):
                render_ass(**base,hook="",punchline="うん")
            with self.assertRaises(ValueError):
                render_ass(**base,hook="うん",punchline="")

if __name__=="__main__":
    unittest.main()
