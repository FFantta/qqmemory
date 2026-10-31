import tempfile
import threading
import unittest
from pathlib import Path
from qqmemory.parallel import process_media
from qqmemory.storage import Archive


class ParallelTests(unittest.TestCase):
    def test_concurrent_workers_use_independent_connections(self):
        barrier = threading.Barrier(4, timeout=5)
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(directory)
            archive.ingest([dict(source='test', record_key='a', source_id='a',
                                 content='a', photos=[['https://a.qpic.cn/'+str(i)] for i in range(4)])])
            ids = [r['id'] for r in archive.db.execute('SELECT id FROM media')]
            def worker(mid):
                local = Archive(directory)
                try:
                    barrier.wait()
                    with local.db:
                        local.db.execute("UPDATE media SET state='failed',error='test' WHERE id=?", (mid,))
                    return None
                finally:
                    local.close()
            progress = []
            self.assertEqual(process_media(ids, worker, lambda *args: progress.append(args)), (0, 4))
            self.assertEqual(progress[-1], (4, 4, 0, 4))
            self.assertEqual(archive.db.execute("SELECT count(*) FROM media WHERE state='failed'").fetchone()[0], 4)
            archive.close()

class PipelineTests(unittest.TestCase):
    def test_starts_during_collection_and_deduplicates(self):
        from qqmemory.parallel import MediaPipeline
        ready = threading.Barrier(4, timeout=5)
        release = threading.Event()
        calls = []
        lock = threading.Lock()
        def worker(mid):
            with lock:
                calls.append(mid)
            ready.wait()
            release.wait(5)
            return 'saved'
        pipeline = MediaPipeline(worker, lambda *args: None, workers=3)
        try:
            pipeline.enqueue(['a','b','c'])
            ready.wait()  # Downloads are active before collection has finished.
            pipeline.enqueue(['a','b'])
            self.assertEqual(len(pipeline.futures), 3)
            self.assertEqual(len(calls), 3)
        finally:
            release.set()
            self.assertEqual(pipeline.finish(), (3, 0, 0))

    def test_failed_image_does_not_block_others_or_exceed_budget(self):
        from qqmemory.parallel import MediaPipeline
        def worker(mid):
            return None if mid == 'bad' else 'saved'
        updates = []
        pipeline = MediaPipeline(worker, lambda *args: updates.append(args), workers=2, limit=3)
        pipeline.enqueue(['bad','good','also-good','not-scheduled'])
        self.assertEqual(pipeline.finish(), (2, 1, 0))
        self.assertEqual(updates[-1], (3, 3, 2, 1))

    def test_finish_handles_already_cancelled_future(self):
        from concurrent.futures import Future
        from qqmemory.parallel import MediaPipeline
        pipeline = MediaPipeline(lambda _: 'saved', lambda *args: None, workers=1)
        future = Future()
        future.cancel()
        pipeline.futures['cancelled'] = future
        finished = threading.Event()
        result = []
        def finish():
            result.append(pipeline.finish(cancel=True))
            finished.set()
        thread = threading.Thread(target=finish, daemon=True)
        thread.start()
        self.assertTrue(finished.wait(2), 'Cancelled futures must not hang shutdown')
        self.assertEqual(result, [(0, 0, 1)])
