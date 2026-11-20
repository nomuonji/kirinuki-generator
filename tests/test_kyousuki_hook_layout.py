import tempfile
import unittest
from pathlib import Path
from scripts.kyousuki_rebuild_from_source import ass_file, editorial_hook


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

    def test_hook_requires_editorial_text(self):
        with self.assertRaises(ValueError):
            editorial_hook("")
        self.assertIn("想い",editorial_hook("ケイの**想い**"))

if __name__ == "__main__":
    unittest.main()
