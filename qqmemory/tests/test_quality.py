import io
import json
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from qqmemory.storage import Archive
from qqmemory.media import download
from qqmemory.quality import candidates, attempts


def picture(size):
    data = io.BytesIO()
    Image.new("RGB", size, "red").save(data, format="PNG")
    return data.getvalue()


class QualityTests(unittest.TestCase):
    def test_media_only_does_not_collect_posts(self):
        from types import SimpleNamespace
        from qqmemory.trial import run_trial

        with tempfile.TemporaryDirectory() as root:
            qq = SimpleNamespace(uin="123")
            qq.data = lambda *_: self.fail("media-only must not collect text")
            output, report = run_trial(
                qq, root, threading.Event(), lambda *_: None, media_only=True
            )
            self.assertTrue(output.exists())
            self.assertEqual(report["requests"], 0)
            self.assertEqual(report["mode"], "media")

    def test_upgrade_api_uses_media_only_and_refuses_active_task(self):
        from qqmemory.mac_app import Controller, create_server

        with tempfile.TemporaryDirectory() as root:
            controller = Controller(root)
            _, url, app = create_server(controller, bind=False)
            prefix = "/" + url.split("/")[-2]
            with patch.object(controller, "start") as start:
                client = app.test_client()
                self.assertEqual(client.post(prefix + "/api/upgrade", json={}).status_code, 200)
                start.assert_called_once_with(6, mode="media")
                controller.active = True
                self.assertEqual(client.post(prefix + "/api/upgrade", json={}).status_code, 409)

    def test_hd_candidate_keeps_fallback_and_signature(self):
        url = "https://m.qpic.cn/psc?/sample/sig/m&bo=123&token=kept"
        result = candidates([url])
        self.assertEqual(result, [url.replace("/m&", "/q&"), url])
        other = "https://example.com/psc?/sample/m&bo=123"
        self.assertEqual(candidates([other]), [])
        store = "http://photogz.photo.store.qq.com/psc?/sample/sig/m&bo=123"
        result = candidates([store])
        self.assertEqual(result[0], store.replace("http:", "https:").replace("/m&", "/q&"))
        self.assertEqual(result[1], store.replace("http:", "https:"))

    def test_bounded_attempts_keep_original_fallback(self):
        urls = [f"https://a.qpic.cn/psc?/sig{i}/m&bo=123" for i in range(8)]
        planned = attempts(urls)
        self.assertEqual(len(planned), 4)
        self.assertEqual(planned[-1], urls[0])
        with tempfile.TemporaryDirectory() as root:
            a = Archive(root)
            try:
                a.ingest(
                    [dict(source="test", record_key="p", source_id="p", content="", photos=[urls])]
                )

                def fetch(url):
                    if "/q&" in url:
                        raise OSError("expired")
                    return picture((20, 20))

                self.assertIsNotNone(download(a, a.posts()[0]["media"][0]["id"], fetch))
            finally:
                a.close()

    def test_choose_largest_then_upgrade_existing_cache_without_losing_old_file(self):
        with tempfile.TemporaryDirectory() as root:
            a = Archive(root)
            try:
                a.ingest(
                    [
                        dict(
                            source="test",
                            record_key="p",
                            source_id="p",
                            content="photo",
                            photos=[["https://a.qpic.cn/small", "https://a.qpic.cn/large"]],
                        )
                    ]
                )
                mid = a.posts()[0]["media"][0]["id"]
                first = download(
                    a, mid, lambda url: picture((10, 10) if url.endswith("small") else (30, 30))
                )
                self.assertEqual(a.db.execute("SELECT width FROM media").fetchone()[0], 30)
                with a.db:
                    a.db.execute(
                        "UPDATE media SET candidates=? WHERE id=?",
                        (json.dumps(["https://a.qpic.cn/full"]), mid),
                    )
                second = download(a, mid, lambda _: picture((60, 60)))
                self.assertNotEqual(first, second)
                self.assertTrue((Path(root) / first).exists())
                self.assertEqual(a.db.execute("SELECT width FROM media").fetchone()[0], 60)
                self.assertEqual(
                    download(
                        a, mid, lambda _: self.fail("checked cache should not request network")
                    ),
                    second,
                )
                with a.db:
                    a.db.execute("UPDATE media SET quality_checked=NULL")
                self.assertEqual(download(a, mid, lambda _: picture((20, 20))), second)
                self.assertEqual(a.db.execute("SELECT width FROM media").fetchone()[0], 60)
            finally:
                a.close()

    def test_failed_hd_upgrade_preserves_saved_image(self):
        with tempfile.TemporaryDirectory() as root:
            a = Archive(root)
            try:
                a.ingest(
                    [
                        dict(
                            source="test",
                            record_key="p",
                            source_id="p",
                            content="",
                            photos=[["https://a.qpic.cn/a"]],
                        )
                    ]
                )
                mid = a.posts()[0]["media"][0]["id"]
                original = download(a, mid, lambda _: picture((20, 20)))
                with a.db:
                    a.db.execute("UPDATE media SET quality_checked=NULL")

                def fail(_):
                    raise OSError("offline")

                self.assertEqual(download(a, mid, fail), original)
                self.assertEqual(a.db.execute("SELECT state FROM media").fetchone()[0], "saved")
            finally:
                a.close()
