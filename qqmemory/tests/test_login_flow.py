"""Synthetic QR tasks: ownership, immutable settings, and image-only admission."""

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from qqmemory.mac_app import Controller, create_server
from qqmemory.storage import Archive


class LoginFlowTests(unittest.TestCase):
    def setup_archive(self, root, photos):
        archive = Archive(Path(root) / "123")
        archive.ingest(
            [
                dict(
                    source="visible",
                    record_key="one",
                    source_id="one",
                    content="synthetic",
                    photos=photos,
                )
            ]
        )
        archive.close()
        controller = Controller(root)
        _, _, app = create_server(controller, bind=False, token="a" * 43)
        return controller, app.test_client(), "/" + "a" * 43

    def test_no_missing_photos_skips_login_and_no_account_is_explained(self):
        with tempfile.TemporaryDirectory() as root:
            c, client, prefix = self.setup_archive(root, [])
            with patch(
                "qqmemory.mac_app.QQSession", side_effect=AssertionError("No network allowed")
            ):
                self.assertFalse(client.post(prefix + "/api/upgrade", json={}).json["started"])
                self.assertFalse(c.active)
                c.account = None
                response = client.post(prefix + "/api/upgrade", json={})
                self.assertEqual(response.status_code, 400)
                self.assertIn("添加账号", response.json["error"])

    def test_login_settings_are_frozen_and_stale_cancel_cannot_stop_new_task(self):
        with tempfile.TemporaryDirectory() as root:
            c, client, prefix = self.setup_archive(root, [["https://a.qpic.cn/example.jpg"]])
            entered = threading.Event()

            def qr():
                entered.set()
                return b"synthetic-qr"

            qq = SimpleNamespace(uin="", qr=qr, poll=lambda: "66", close=Mock())
            with patch("qqmemory.mac_app.QQSession", return_value=qq):
                result = client.post(prefix + "/api/upgrade", json={"workers": 2}).json
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(c.media_workers, 2)
                    self.assertEqual(c.mode, "media")
                    task = result["task_id"]
                    self.assertEqual(client.get(prefix + "/api/state").json["task_id"], task)
                    self.assertEqual(
                        client.post(
                            prefix + "/api/start", json={"workers": 12, "mode": "deep"}
                        ).status_code,
                        409,
                    )
                    self.assertEqual(c.mode, "media")
                    self.assertEqual(c.media_workers, 2)
                    self.assertEqual(
                        client.post(prefix + "/api/stop", json={"task_id": "stale"}).status_code,
                        409,
                    )
                    self.assertFalse(c.stop.is_set())
                    self.assertEqual(
                        client.post(
                            prefix + "/api/qr/refresh", json={"task_id": "stale"}
                        ).status_code,
                        409,
                    )
                    self.assertEqual(
                        client.post(prefix + "/api/stop", json={"task_id": task}).status_code, 200
                    )
                finally:
                    c.stop.set()
                    c.thread.join(3)
            self.assertFalse(c.active)

    def test_invalid_worker_settings_are_actionable(self):
        with tempfile.TemporaryDirectory() as root:
            _, client, prefix = self.setup_archive(root, [])
            for path in ("start", "upgrade"):
                for value in (None, "invalid", 0, 13):
                    result = client.post(prefix + "/api/" + path, json={"workers": value})
                    self.assertEqual(result.status_code, 400)
                    self.assertIn("error", result.json)
