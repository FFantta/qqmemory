import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from qqmemory.emoji import emoji_html, get_emoji


class EmojiTests(unittest.TestCase):
    def test_tokens_escaped_text_and_unicode(self):
        value = emoji_html(
            "<script>x</script>🥹[em]e142[/em][em]e402399[/em]",
            lambda c: "assets/emoji/" + c + ".gif",
        )
        self.assertIn("&lt;script&gt;", value)
        self.assertIn("🥹", value)
        self.assertEqual(value.count('class="qq-emoji"'), 2)
        self.assertNotIn("[em]", value)
        self.assertIn("e402399.gif", value)

    def test_missing_asset_is_visible_and_paths_are_rejected(self):
        self.assertIn("〔表情〕", emoji_html("[em]e142[/em]", lambda _: None))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                get_emoji("../../private", root)

    def test_validated_cache_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            data = io.BytesIO()
            Image.new("RGB", (20, 20), "yellow").save(data, format="GIF")
            response = MagicMock()
            response.__enter__.return_value = response
            response.status_code = 200
            response.raw.read.return_value = data.getvalue()
            with patch("qqmemory.emoji.requests.get", return_value=response) as request:
                first = get_emoji("e142", root)
                self.assertTrue(first.is_file())
                self.assertEqual(get_emoji("e142", root), first)
                self.assertEqual(request.call_count, 1)

    def test_offline_export_copies_cached_emoji(self):
        from qqmemory.storage import Archive
        from qqmemory.exporting import export_archive

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "emojis").mkdir()
            Image.new("RGB", (24, 24), "yellow").save(root / "emojis/e142.gif", format="GIF")
            archive = Archive(root / "archive")
            try:
                archive.ingest(
                    [
                        dict(
                            source="synthetic",
                            record_key="one",
                            source_id="one",
                            content="你好[em]e142[/em]🥹",
                            photos=[],
                        )
                    ]
                )
                out = export_archive(archive, root / "export")
                page = (out / "index.html").read_text(encoding="utf-8")
                self.assertIn("assets/emoji/e142.gif", page)
                self.assertNotIn("[em]e142[/em]", page)
                self.assertTrue((out / "assets/emoji/e142.gif").is_file())
            finally:
                archive.close()

    def test_cloud_export_copies_avatar_emoji_and_keeps_text_only_posts(self):
        from qqmemory.storage import Archive
        from qqmemory.exporting import export_archive
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "avatars").mkdir()
            (root / "emojis").mkdir()
            Image.new("RGB", (24, 24), "yellow").save(root / "emojis/e142.gif", format="GIF")
            Image.new("RGB", (24, 24), "blue").save(root / "avatars/123.img", format="PNG")
            archive = Archive(root / "123")
            try:
                archive.ingest(
                    [
                        dict(
                            source="synthetic",
                            record_key="one",
                            source_id="one",
                            content="纯文字[em]e142[/em]🥹 @{uin:456,nick:好友,who:1}",
                            photos=[],
                        )
                    ]
                )
                with patch("qqmemory.export_assets.prepare_assets") as prepare:
                    out = export_archive(archive, root / "export", fetch_assets=True)
                    self.assertEqual(prepare.call_count, 1)
                page = (out / "index.html").read_text(encoding="utf-8")
                self.assertIn("media/avatars/123.jpg", page)
                self.assertIn("media/emoji/e142.gif", page)
                self.assertIn("QQ：456", page)
                self.assertIn(".person:hover:after", page)
                self.assertIn("纯文字", page)
                self.assertNotIn("<!-- ARCHIVE_CARDS -->", page)
                self.assertEqual(page.count("<article "), 1)
                self.assertTrue((out / "media/avatars/123.jpg").is_file())
                self.assertTrue((out / "media/emoji/e142.gif").is_file())
            finally:
                archive.close()

    def test_cloud_assets_use_public_request_without_login_cookies(self):
        from qqmemory.export_assets import prepare_assets

        with tempfile.TemporaryDirectory() as root:
            data = io.BytesIO()
            Image.new("RGB", (20, 20), "blue").save(data, format="PNG")
            response = MagicMock()
            response.__enter__.return_value = response
            response.raw.read.return_value = data.getvalue()
            with (
                patch("qqmemory.export_assets.requests.get", return_value=response) as get,
                patch("qqmemory.export_assets.get_emoji") as emoji,
            ):
                prepare_assets([{"author": {"uin": "123"}, "content": "[em]e142[/em]"}], root)
                self.assertTrue((Path(root) / "avatars/123.img").is_file())
                self.assertEqual(emoji.call_count, 1)
                self.assertEqual(get.call_args.kwargs["params"]["nk"], "123")
                self.assertNotIn("cookies", get.call_args.kwargs)
                self.assertFalse(get.call_args.kwargs["allow_redirects"])
