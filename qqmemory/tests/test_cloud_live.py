import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from qqmemory.cloud_app import CloudService, create_cloud_app
from qqmemory.media import download
from qqmemory.parallel import MediaPipeline
from qqmemory.storage import Archive
from qqmemory.exporting import export_archive
from test_cloud import FakeQQ, fake_runner, SECRET


def picture(size=(4, 4)):
    stream = io.BytesIO()
    Image.new("RGB", size, "red").save(stream, format="PNG")
    return stream.getvalue()


class FirstImageTests(unittest.TestCase):
    def test_first_success_is_saved_without_checking_other_versions_then_can_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory) / "123")
            self.addCleanup(archive.close)
            archive.ingest(
                [
                    dict(
                        source="test",
                        record_key="p",
                        source_id="p",
                        content="hi",
                        photos=[
                            [
                                "https://a.qpic.cn/psc?/image/q&bo=1",
                                "https://a.qpic.cn/psc?/image/m&bo=1",
                            ]
                        ],
                    )
                ]
            )
            mid = archive.db.execute("SELECT id FROM media").fetchone()[0]
            calls = []

            def fetch(url):
                calls.append(url)
                return picture((12, 12) if "/q&" in url else (4, 4))

            first = download(archive, mid, fetch, quality="first")
            self.assertEqual(len(calls), 1)
            self.assertIn("/m&", calls[0])
            self.assertIsNone(archive.db.execute("SELECT quality_checked FROM media").fetchone()[0])
            self.assertEqual(
                download(
                    archive, mid, lambda _: self.fail("cache must be reused"), quality="first"
                ),
                first,
            )
            export_archive(archive, Path(directory) / "first-export")
            self.assertIn("高清待检查", (Path(directory) / "first-export/index.html").read_text())
            upgraded = download(archive, mid, fetch)
            row = archive.db.execute("SELECT * FROM media").fetchone()
            self.assertEqual(row["width"], 12)
            self.assertTrue(row["quality_checked"])
            self.assertNotEqual(first, upgraded)
            self.assertTrue((archive.root / first).is_file())
            export_archive(archive, Path(directory) / "checked-export")
            self.assertIn(
                "清晰度已检查 · 不保证原图",
                (Path(directory) / "checked-export/index.html").read_text(),
            )

    def test_failed_candidate_falls_back_but_does_not_claim_hd(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            self.addCleanup(archive.close)
            archive.ingest(
                [
                    dict(
                        source="test",
                        record_key="p",
                        source_id="p",
                        content="hi",
                        photos=[
                            [
                                "https://a.qpic.cn/bad",
                                "https://a.qpic.cn/good",
                                "https://a.qpic.cn/extra",
                            ]
                        ],
                    )
                ]
            )
            mid = archive.db.execute("SELECT id FROM media").fetchone()[0]
            calls = []

            def fetch(url):
                calls.append(url)
                return b"bad" if url.endswith("bad") else picture()

            self.assertTrue(download(archive, mid, fetch, quality="first"))
            self.assertEqual(len(calls), 2)
            self.assertIsNone(archive.db.execute("SELECT quality_checked FROM media").fetchone()[0])

    def test_bounded_queue_does_not_block_scanning_and_later_drains_pending(self):
        started, release = threading.Event(), threading.Event()
        saved = []

        def worker(mid):
            started.set()
            release.wait(3)
            saved.append(mid)
            return True

        pipeline = MediaPipeline(worker, lambda *_: None, workers=1, max_pending=1)
        try:
            pipeline.enqueue(["first", "later"], block=False)
            self.assertTrue(started.wait(1))
            self.assertEqual(pipeline.seen, {"first"})
            # The collector reaches this point while the first image is still in flight.
            release.set()
            pipeline.enqueue(["first", "later"], block=True)
            self.assertEqual(pipeline.finish(), (2, 0, 0))
            self.assertEqual(saved, ["first", "later"])
        finally:
            release.set()
            pipeline.pool.shutdown(wait=True, cancel_futures=True)

    def test_scan_continues_while_first_image_is_downloading(self):
        from qqmemory.trial import run_trial, TrialLimits
        from test_trial_protocol import ImmediateStop

        started, second_page = threading.Event(), threading.Event()

        class QQ:
            uin = "123"
            token = "test"

            def data(inner, url, params):
                if "get_feeds" in url:
                    return {"data": {"vFeeds": []}}
                pos = params["pos"]
                if pos:
                    self.assertTrue(started.wait(2))
                    second_page.set()
                return {
                    "total": 31,
                    "msglist": [
                        dict(
                            tid=str(pos + i),
                            uin=123,
                            content="text",
                            created_time=1500000000,
                            pic=[{"url1": "https://a.qpic.cn/a"}],
                        )
                        for i in range(30 if pos == 0 else 1)
                    ],
                }

        def downloader(archive, mid, transport, **kwargs):
            started.set()
            self.assertTrue(
                second_page.wait(2), "download must not block fetching the next text page"
            )
            self.assertEqual(kwargs["quality"], "first")
            return False

        with (
            tempfile.TemporaryDirectory() as root,
            patch("qqmemory.trial.download", side_effect=downloader),
        ):
            output, report = run_trial(
                QQ(),
                root,
                ImmediateStop(),
                lambda *_: None,
                backup_only=True,
                text_first=True,
                media_quality="first",
                media_max_pending=1,
                media_workers=1,
                limits=TrialLimits(scan_seconds=30, total_seconds=60, requests=4, media=40),
            )
            self.assertTrue(output.is_file())
            self.assertEqual(report["exported_posts"], 31)
            self.assertEqual(report["media_failed_this_run"], 31)
            self.assertFalse(report["text_first"])


class LivePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.initial_options = []

        def initial_runner(qq, root, stop, notify, **kwargs):
            self.initial_options.append(kwargs)
            return fake_runner(qq, root, stop, notify)

        self.service = CloudService(
            self.temp.name, SECRET, qq_factory=FakeQQ, runner=initial_runner, poll_seconds=0.001
        )
        self.app = create_cloud_app(
            secret=SECRET, service=self.service, testing=True, cleaner=False
        )
        self.client = self.app.test_client()
        csrf = self.client.get("/api/session").json["csrf"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
        response = self.client.post("/api/jobs", json={"consent": True}, headers=self.headers)
        self.job = self.service.jobs[response.json["id"]]
        self.job.thread.join(3)
        self.assertFalse(self.job.active)
        self.base = "/api/jobs/" + self.job.id
        archive = Archive(self.job.root / "123")
        archive.ingest(
            [
                dict(
                    source="test",
                    record_key=str(i),
                    source_id=str(i),
                    content="<script>private</script>",
                    photos=[["https://a.qpic.cn/private-signed-url"]] if i == 0 else [],
                )
                for i in range(25)
            ]
        )
        self.mid = archive.db.execute("SELECT id FROM media").fetchone()[0]
        download(archive, self.mid, lambda _: picture(), quality="first")
        archive.close()

    def test_preview_while_running_has_bounded_rows_and_no_source_urls(self):
        self.job.output = None
        self.job.active = True
        self.addCleanup(setattr, self.job, "active", False)
        response = self.client.get(self.base + "/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["posts"]), 20)
        self.assertEqual(response.json["total"], 25)
        self.assertEqual(len(self.client.get(self.base + "/live?offset=20").json["posts"]), 5)
        self.assertNotIn("qpic.cn", response.text)
        self.assertNotIn("private-signed-url", response.text)
        self.assertEqual(self.client.get(self.base + "/live?offset=bad").status_code, 400)
        image = self.client.get(self.base + "/media/" + self.mid)
        self.assertEqual(image.status_code, 200)
        image.close()
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_other_browser_and_deleted_job_cannot_read_live_content_or_images(self):
        other = self.app.test_client()
        for path in ("/live", "/media/" + self.mid):
            self.assertEqual(other.get(self.base + path).status_code, 404)
        self.service.delete(self.job)
        self.assertEqual(self.client.get(self.base + "/live").status_code, 404)
        self.assertEqual(self.client.get(self.base + "/media/" + self.mid).status_code, 404)

    def test_live_image_refuses_outside_archive_media(self):
        import sqlite3

        db = sqlite3.connect(self.job.root / "123/archive.sqlite3")
        try:
            with db:
                db.execute("UPDATE media SET local_path='../job.json' WHERE id=?", (self.mid,))
        finally:
            db.close()
        self.assertEqual(self.client.get(self.base + "/media/" + self.mid).status_code, 404)

    def test_quality_continuation_is_explicit_and_persists_mode(self):
        captured = []

        def runner(qq, root, stop, notify, **kwargs):
            captured.append(kwargs)
            return fake_runner(qq, root, stop, notify)

        self.service.runner = runner
        response = self.client.post(
            self.base + "/continue", json={"quality_only": True}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.job.thread.join(3)
        self.assertTrue(captured[0]["media_only"])
        self.assertEqual(captured[0]["media_quality"], "best")
        self.assertFalse(captured[0]["deep"])
        persisted = json.loads((self.job.root / "job.json").read_text())
        self.assertEqual(persisted["mode"], "quality")
        response = self.client.post(
            self.base + "/continue", json={"quality_only": "yes"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_normal_cloud_collection_enables_fast_overlapping_downloads(self):
        self.assertEqual(self.initial_options[0]["media_quality"], "first")
        self.assertFalse(self.initial_options[0]["media_only"])
        self.assertTrue(self.initial_options[0]["deep"])
