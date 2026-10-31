import tempfile
import unittest
from pathlib import Path
from qqmemory.storage import Archive
from qqmemory.statistics import archive_statistics, format_statistics
from qqmemory.exporting import export_archive


class StatisticsTests(unittest.TestCase):
    def test_unknown_post_time_is_not_replaced_by_interaction(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory) / "archive")
            try:
                archive.ingest(
                    [
                        dict(
                            source="history",
                            record_key="h",
                            source_id="h",
                            content="old",
                            photos=[["https://a.qpic.cn/p"]],
                            interaction_time="1356998400",
                        )
                    ]
                )
                data = archive_statistics(archive.root / "archive.sqlite3")
                self.assertEqual(data["posts"], 1)
                self.assertEqual(data["earliest"], "未知")
                self.assertEqual(data["earliest_interaction"], "2013-01-01")
                self.assertEqual(data["photos_pending"], 1)
                self.assertIn("不是原帖时间", format_statistics(data))
                progress = []
                out = export_archive(archive, Path(directory) / "export", progress.append)
                self.assertTrue(out.is_dir())
                self.assertTrue(any("正在导出照片 1/1" in x for x in progress))
                self.assertIn("1 条说说、0 张照片", progress[-1])
            finally:
                archive.close()
