"""Bounded parallel media work; each task owns its database connection."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time


def process_media(ids, worker, progress, workers=4):
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qzone-media") as pool:
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

    def __init__(self, worker, progress, workers=6, limit=300, max_pending=None, should_stop=None):
        if not 1 <= workers <= 12:
            raise ValueError("Media concurrency must be between 1 and 12")
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qzone-media")
        self.worker = worker
        self.progress = progress
        self.limit = limit
        self.futures = {}
        self.capacity = threading.BoundedSemaphore(max_pending) if max_pending else None
        self.should_stop = should_stop or (lambda: False)
        self.seen = set()
        self.completed = [0, 0, 0]
        self.reported = 0

    def compact(self):
        if not self.capacity:
            return
        for mid, future in list(self.futures.items()):
            if future.done():
                index = (
                    2
                    if future.cancelled() or future.exception() is not None
                    else 0
                    if future.result()
                    else 1
                )
                self.completed[index] += 1
                del self.futures[mid]

    def enqueue(self, ids):
        for mid in ids:
            self.compact()
            self.heartbeat()
            if mid not in self.seen and mid not in self.futures and len(self.seen) < self.limit:
                if self.capacity:
                    while not self.capacity.acquire(timeout=0.25):
                        self.heartbeat()
                        if self.should_stop():
                            return self.report()
                    if self.should_stop():
                        self.capacity.release()
                        return self.report()
                self.seen.add(mid)
                try:
                    future = self.pool.submit(self.worker, mid)
                except BaseException:
                    if self.capacity:
                        self.capacity.release()
                    raise
                self.futures[mid] = future
                if self.capacity:
                    future.add_done_callback(lambda _: self.capacity.release())
        self.report()

    def heartbeat(self):
        if time.monotonic() - self.reported >= 1:
            self.report()

    def report(self):
        self.reported = time.monotonic()
        saved, failed, interrupted = self.completed
        for future in self.futures.values():
            if not future.done():
                continue
            if future.cancelled() or future.exception() is not None:
                interrupted += 1
            elif future.result():
                saved += 1
            else:
                failed += 1
        self.progress(
            saved + failed + interrupted,
            max(len(self.seen), sum(self.completed) + len(self.futures)),
            saved,
            failed,
        )
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
