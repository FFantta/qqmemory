import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from qqmemory.storage import Archive
from qqmemory.mac_app import Controller, create_server
from qqmemory.progress import TaskProgress
from qqmemory.trial import run_trial
from qqmemory.online import MOODS


def fixture(root, uin, text):
    a = Archive(Path(root) / uin)
    a.ingest([dict(source="visible", record_key=text, source_id=text, content=text, photos=[])])
    a.close()


class AccountTests(unittest.TestCase):
    def test_local_switch_never_logs_in_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root, "123", "first")
            fixture(root, "456", "second")
            c = Controller(root)
            _, _, app = create_server(c, bind=False, token="a" * 43)
            client = app.test_client()
            prefix = "/" + "a" * 43
            with patch(
                "qqmemory.mac_app.QQSession",
                side_effect=AssertionError("local switch must be offline"),
            ):
                accounts = client.get(prefix + "/api/accounts").json["accounts"]
                self.assertEqual({p["uin"] for p in accounts}, {"123", "456"})
                self.assertEqual(
                    client.post(prefix + "/api/accounts/select", json={"uin": "456"}).status_code,
                    200,
                )
                state = client.get(prefix + "/api/state").json
                self.assertEqual(state["account"], "456")
                self.assertEqual(state["posts"][0]["content"], "second")
                self.assertEqual(Controller(root).account, "456")
                self.assertEqual(
                    client.post(
                        prefix + "/api/accounts/select", json={"uin": "../123"}
                    ).status_code,
                    400,
                )
                self.assertEqual(
                    client.post(prefix + "/api/accounts/select", json={"uin": {}}).status_code, 400
                )

    def test_view_switch_keeps_running_task_bound_to_original_account(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root, "123", "first")
            fixture(root, "456", "second")
            c = Controller(root)
            started, release = threading.Event(), threading.Event()

            def run(qq, *args, **kwargs):
                started.set()
                release.wait(3)
                self.assertEqual(qq.uin, "123")
                return Path(root) / "out.html", dict(
                    state="completed", exported_posts=1, exported_photos=0, issues=[]
                )

            with (
                patch(
                    "qqmemory.mac_app.QQSession",
                    return_value=SimpleNamespace(uin="123", nickname="first", close=Mock()),
                ),
                patch("qqmemory.mac_app.run_trial", side_effect=run),
            ):
                c.start(6, mode="backup")
                try:
                    self.assertTrue(started.wait(2))
                    c.switch_account("456")
                    self.assertEqual(c.account, "456")
                    self.assertEqual(c.task_account, "123")
                    a = c.read_archive()
                    self.assertEqual(
                        a.db.execute("SELECT content FROM posts").fetchone()[0], "second"
                    )
                    a.db.close()
                finally:
                    release.set()
                    c.thread.join(3)
            self.assertEqual(c.account, "456")
            self.assertEqual(c.outcome, "completed")

    def test_wrong_qr_account_cannot_update_selected_archive(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root, "123", "first")
            c = Controller(root)
            fresh = SimpleNamespace(uin="456", close=Mock())
            with (
                patch("qqmemory.mac_app.QQSession", return_value=fresh),
                patch("qqmemory.mac_app.run_trial") as run,
            ):
                c.start(6)
                c.thread.join(2)
                run.assert_not_called()
            self.assertEqual(c.account, "123")
            self.assertFalse((Path(root) / "456").exists())
            self.assertEqual(c.phase, "error")
            fresh.close.assert_called_once()

    def test_backup_mode_skips_historical_scan(self):
        class QQ:
            uin = "123"
            token = "x"

            def data(self, url, params):
                if url == MOODS:
                    return {"total": 0, "msglist": []}
                if url == "https://mobile.qzone.qq.com/get_feeds":
                    return {"data": {"vFeeds": []}}
                raise AssertionError("backup should not scan history")

        class Stop:
            def is_set(self):
                return False

            def wait(self, n):
                return False

            def set(self):
                pass

        with tempfile.TemporaryDirectory() as root:
            _, report = run_trial(QQ(), root, Stop(), lambda *args: None, backup_only=True)
            self.assertEqual(report["state"], "completed")
            self.assertEqual(report["requests"], 2)


class ProgressTests(unittest.TestCase):
    def test_eta_requires_samples_and_stops_advancing_after_finish(self):
        now = [100.0]
        p = TaskProgress(clock=lambda: now[0])
        p.update(dict(stage="deep", done=100, total=1000))
        now[0] += 2
        p.update(dict(stage="deep", done=102, total=1000))
        self.assertIsNone(p.snapshot(True, "collecting")["eta"])
        now[0] += 18
        p.update(dict(stage="deep", done=110, total=1000))
        s = p.snapshot(True, "collecting")
        self.assertEqual(s["percent"], 11)
        self.assertEqual(s["eta"], [890, 3560])
        p.finish()
        now[0] += 100
        self.assertEqual(p.snapshot(False, "done")["elapsed"], 20)
        self.assertIsNone(p.snapshot(False, "done")["eta"])
        self.assertEqual(p.snapshot(True, "stopping")["state"], "stopping")

    def test_changed_stage_or_retry_plan_resets_rate_samples(self):
        now = [100.0]
        p = TaskProgress(clock=lambda: now[0])
        p.update(dict(stage="deep", done=100, total=1000))
        now[0] += 30
        p.update(dict(stage="deep", done=120, total=1000))
        self.assertIsNotNone(p.snapshot(True, "collecting")["eta"])
        p.update(dict(stage="deep", done=0, total=20))
        self.assertIsNone(p.snapshot(True, "collecting")["eta"])
        p.update(dict(stage="media"))
        self.assertIsNone(p.snapshot(True, "collecting")["percent"])
