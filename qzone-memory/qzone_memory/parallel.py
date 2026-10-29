"""Bounded parallel media work; each task owns its database connection."""
from concurrent.futures import ThreadPoolExecutor, as_completed


def process_media(ids, worker, progress, workers=4):
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='qzone-media') as pool:
        futures = [pool.submit(worker, mid) for mid in ids]
        saved = failed = 0
        try:
            for completed, future in enumerate(as_completed(futures), 1):
                if future.result():
                    saved += 1
                else:
                    failed += 1
                progress(completed, len(ids), saved, failed)
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return saved, failed


class MediaPipeline:
    """Submit discoveries during collection; drain before exporting a stable archive."""
    def __init__(self, worker, progress, workers=6, limit=300):
        if not 1 <= workers <= 12:
            raise ValueError('Media concurrency must be between 1 and 12')
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='qzone-media')
        self.worker = worker
        self.progress = progress
        self.limit = limit
        self.futures = {}

    def enqueue(self, ids):
        for mid in ids:
            if mid not in self.futures and len(self.futures) < self.limit:
                self.futures[mid] = self.pool.submit(self.worker, mid)
        self.report()

    def report(self):
        saved = failed = interrupted = 0
        for future in self.futures.values():
            if not future.done():
                continue
            if future.cancelled() or future.exception() is not None:
                interrupted += 1
            elif future.result():
                saved += 1
            else:
                failed += 1
        self.progress(saved + failed + interrupted, len(self.futures), saved, failed)
        return saved, failed, interrupted

    def finish(self, cancel=False):
        if cancel:
            for future in self.futures.values():
                future.cancel()
        try:
            for future in as_completed([f for f in self.futures.values() if not f.cancelled()]):
                self.report()
        finally:
            self.pool.shutdown(wait=True, cancel_futures=cancel)
        return self.report()
