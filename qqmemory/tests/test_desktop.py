import tempfile
import unittest
from pathlib import Path
from qqmemory.storage import Archive
from qqmemory.timeline import timeline
from qqmemory.online import mobile_record
from qqmemory.mac_app import Controller, create_server


class DesktopTests(unittest.TestCase):
    def test_time_fallback_and_stable_sort(self):
        with tempfile.TemporaryDirectory() as root:
            a = Archive(root)
            try:
                a.ingest(
                    [
                        dict(
                            source="history",
                            record_key="old",
                            source_id="old",
                            content="old",
                            photos=[],
                            interaction_time=1325376000,
                        ),
                        dict(
                            source="visible",
                            record_key="new",
                            source_id="new",
                            content="new",
                            photos=[],
                            published_at="2022-01-01T00:00:00+00:00",
                        ),
                        dict(
                            source="history",
                            record_key="earlier",
                            source_id="old",
                            content="old",
                            photos=[],
                            interaction_time=1293840000,
                        ),
                    ]
                )
                posts = timeline(a)["posts"]
                self.assertEqual([p["source_id"] for p in posts], ["new", "old"])
                self.assertEqual(posts[1]["year"], "2011")
                self.assertEqual(posts[1]["time_basis"], "interaction")
                self.assertIsNone(posts[1]["published_at"])
            finally:
                a.close()

    def test_private_local_api_and_saved_media(self):
        with tempfile.TemporaryDirectory() as root:
            a = Archive(Path(root) / "123")
            a.ingest(
                [
                    dict(
                        source="visible",
                        record_key="x",
                        source_id="x",
                        content="<script>test</script>",
                        photos=[],
                    )
                ]
            )
            a.close()
            controller = Controller(root)
            server, url, app = create_server(controller, bind=False)
            prefix = "/" + url.split("/")[-2]
            try:
                client = app.test_client()
                self.assertEqual(client.get("/api/state").status_code, 404)
                response = client.get(prefix + "/api/state")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["posts"][0]["content"], "<script>test</script>")
                self.assertNotIn("candidates", str(response.json))
                self.assertEqual(
                    client.post(
                        prefix + "/api/stop", json={}, headers={"Origin": "https://evil.example"}
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    client.get(prefix + "/media/../../archive.sqlite3").status_code, 404
                )
            finally:
                if server:
                    server.server_close()

    def test_mobile_ownership_multi_candidates_and_comments(self):
        feed = {
            "comm": {"time": 1451606400},
            "original": {
                "cell_id": {"cellid": "tid"},
                "cell_userinfo": {"user": {"uin": 123, "nickname": "测试"}},
                "cell_summary": {"summary": "正文"},
                "pictures": [
                    {
                        "busi_param": {"-1": "https://a.qpic.cn/full"},
                        "photourl": {"1": {"url": "https://a.qpic.cn/small"}},
                    }
                ],
                "cell_comment": {
                    "comments": [{"user": {"uin": 456, "nickname": "好友"}, "content": "评论"}]
                },
            },
        }
        self.assertIsNone(mobile_record(feed, "999"))
        record = mobile_record(feed, "123")
        self.assertEqual(len(record["photos"][0]), 2)
        self.assertEqual(record["comments"][0]["content"], "评论")
        self.assertIsNone(record["published_at"])

    def test_collection_lock_rejects_second_writer(self):
        from qqmemory.locking import collection_lock, CollectionBusy

        with tempfile.TemporaryDirectory() as directory:
            with collection_lock(directory):
                with self.assertRaises(CollectionBusy):
                    with collection_lock(directory):
                        pass
            with collection_lock(directory):
                pass
