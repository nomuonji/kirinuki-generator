import tempfile
import unittest
from pathlib import Path
from scripts.kyousuki_rebuild_from_source import ass_file, editorial_hook, wrap_spoken_caption


class KyousukiEditorialHookTests(unittest.TestCase):
    def test_original_hook_preserves_emphasis_not_source_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            ass=Path(tmp)/"subtitles.ass"
            count=ass_file([{"startFrame":0,"endFrame":90,"text":"うん、いいね。"}],
                           4.0,ass,"お絵描きで縮まる**距離**")
            text=ass.read_text(encoding="utf-8")
            self.assertEqual(count,1)
            self.assertIn("お絵描きで縮まる",text)
            self.assertIn("距離",text)
            self.assertIn("Style: Hook",text)
            self.assertIn("Style: Dialogue",text)
            self.assertIn("65,65,516,1",text)
            self.assertNotIn("今天喜欢上你了",text)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:04.00,Hook",text)

    def test_long_editorial_hook_is_wrapped_with_emphasis(self):
        long_hook="気持ちを伝えてくれてるから…**付き合いたい**って思ってる"
        text=editorial_hook(long_hook)
        self.assertIn(r"\\N",text)
        self.assertIn("付き合いたい",text)

    def test_long_spoken_line_is_wrapped_without_cutting_words(self):
        spoken="ちょっと、絵もいいよ。適当。適当でっていうか、伝わるなら"
        rendered=wrap_spoken_caption(spoken)
        self.assertIn(r"\N",rendered)
        self.assertEqual(rendered.split("}",1)[1].replace(r"\N",""),spoken)

    def test_hook_requires_editorial_text(self):
        with self.assertRaises(ValueError):
            editorial_hook("")
        self.assertIn("想い",editorial_hook("ケイの**想い**"))

if __name__ == "__main__":
    unittest.main()
