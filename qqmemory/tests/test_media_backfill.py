import io
import tempfile
import threading
import unittest
from pathlib import Path
from PIL import Image
from qqmemory.storage import Archive
from qqmemory.mac_app import Controller, create_server


class BackfillTests(unittest.TestCase):
    def fixture(self, root):
        archive = Archive(Path(root) / "12345")
        archive.ingest(
            [
                dict(
                    source="visible",
                    record_key="one",
                    source_id="one",
                    content="test",
                    photos=[["https://a.qpic.cn/test.jpg"]],
                )
            ]
        )
        mid = archive.db.execute("SELECT id FROM media").fetchone()[0]
        archive.close()
        return mid

    def test_replayed_pending_downloads_without_qq_and_saved_not_repeated(self):
        with tempfile.TemporaryDirectory() as root:
            mid = self.fixture(root)
            controller = Controller(root)
            entered, release = threading.Event(), threading.Event()
            buf = io.BytesIO()
            Image.new("RGB", (20, 30), "green").save(buf, format="PNG")

            def transport(url):
                entered.set()
                release.wait(3)
                return buf.getvalue()

            self.assertTrue(controller.resume_media(transport=transport))
            try:
                self.assertTrue(entered.wait(3))
                self.assertIn(mid, controller.media_running)
                self.assertFalse(controller.resume_media(transport=transport))
                self.assertIsNone(controller.qq)
            finally:
                release.set()
                controller.thread.join(5)
            self.assertFalse(controller.active)
            self.assertFalse(controller.media_running)
            archive = controller.read_archive()
            self.assertEqual(archive.db.execute("SELECT state FROM media").fetchone()[0], "saved")
            archive.db.close()
            self.assertFalse(controller.resume_media(transport=transport))

    def test_failure_is_not_retried_on_every_start_and_manual_retry_validated(self):
        with tempfile.TemporaryDirectory() as root:
            mid = self.fixture(root)
            controller = Controller(root)

            def unavailable(url):
                raise OSError("offline")

            controller.resume_media(transport=unavailable)
            controller.thread.join(5)
            self.assertFalse(controller.resume_media(transport=unavailable))
            self.assertTrue(controller.resume_media(mid, transport=unavailable))
            controller.thread.join(5)
            _, url, app = create_server(controller, bind=False, token="x" * 43)
            with app.test_client() as client:
                self.assertEqual(
                    client.post(
                        "/" + "x" * 43 + "/api/media/retry", json={"id": "../../x"}
                    ).status_code,
                    400,
                )
                data = client.get("/" + "x" * 43 + "/api/state").get_json()
                self.assertEqual(data["media_running"], [])
                self.assertFalse(data["active"])
