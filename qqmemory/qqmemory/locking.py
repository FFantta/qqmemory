"""OS-backed account locks; released by the OS if the collector exits."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class CollectionBusy(RuntimeError):
    pass


@contextmanager
def collection_lock(account):
    path=Path(account)
    path.mkdir(parents=True,exist_ok=True)
    with (path/'collector.lock').open('a+b') as stream:
        if os.name == 'nt':
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
        try:
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise CollectionBusy('这个账号已有采集任务运行，请先在另一个窗口停止任务') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
