import tempfile
import unittest
from pathlib import Path
from bs4 import BeautifulSoup
from qqmemory.storage import Archive
from qqmemory.exporting import export_archive
from qqmemory.large_export import standalone_html


class OfflineStyleTests(unittest.TestCase):
    def test_export_embeds_shared_app_style_and_keeps_user_template_text_literal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = Archive(root / "123")
            try:
                (archive.root / "profile.json").write_text(
                    '{"nickname": "测试账号 <本人>"}', encoding="utf-8"
                )
                (root / "avatars").mkdir()
                (root / "avatars/123.img").write_bytes(b"synthetic-avatar")
                archive.ingest(
                    [
                        dict(
                            source="visible",
                            record_key="one",
                            source_id="one",
                            content="/* APP_STYLE */ /* OFFLINE_SCRIPT */ <script>alert(1)</script>",
                            published_at="2020-01-01T00:00:00+00:00",
                            photos=[],
                        )
                    ]
                )
                export_archive(archive, root / "export")
                output = root / "export/index.html"
                source = output.read_text(encoding="utf-8")
                page = BeautifulSoup(source, "html.parser")
                self.assertEqual(page.h1.get_text(), "空间记忆 · 离线档案")
                self.assertIn(
                    (Path(__file__).parents[1] / "qqmemory/ui/app.css").read_text(encoding="utf-8"),
                    page.style.get_text(),
                )
                self.assertIn(
                    "/* APP_STYLE */ /* OFFLINE_SCRIPT */ <script>",
                    page.select_one(".content").get_text(),
                )
                self.assertEqual(len(page.select("script")), 1)
                self.assertFalse(page.select("script[src], link[rel=stylesheet]"))
                card = page.select_one("article.card")
                self.assertEqual(card["data-year"], "2020")
                self.assertEqual(card["data-photos"], "false")
                self.assertEqual(page.select_one(".profile strong").get_text(), "测试账号 <本人>")
                avatar = page.select_one(".profile img")
                self.assertEqual((output.parent / avatar["src"]).read_bytes(), b"synthetic-avatar")
                self.assertFalse(page.select("header select"))
                self.assertEqual(page.select_one("#year-filter")["type"], "hidden")
                self.assertEqual(len(page.select(".offline-photos input[type=checkbox]")), 1)
                self.assertIsNotNone(page.select_one("#lightbox"))
                self.assertFalse(page.select("#login, #upgrade, #qr-dialog"))
                standalone_html(output, root / "standalone.html")
                self.assertTrue((root / "standalone.html").exists())
            finally:
                archive.close()
