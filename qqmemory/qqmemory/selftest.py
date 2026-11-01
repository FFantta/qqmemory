"""Offline smoke test of the packaged desktop core, without opening user data."""

import io
import json
from pathlib import Path
import platform
import tempfile
from PIL import Image
from .mac_app import Controller, create_server
from .locking import collection_lock, CollectionBusy
from .storage import Archive
from .exporting import export_archive
from .version import VERSION, release_info


def run(destination):
    with tempfile.TemporaryDirectory(prefix="qqmemory-smoke-") as root:
        root = Path(root)
        controller = Controller(root / "empty")
        _, url, app = create_server(controller, bind=False)
        prefix = "/" + url.split("/")[-2]
        response = app.test_client().get(prefix + "/api/state")
        assert response.status_code == 200 and response.json["account"] is None
        assert response.json["active"] is False
        with collection_lock(root / "123"):
            try:
                with collection_lock(root / "123"):
                    raise AssertionError("Second writer acquired lock")
            except CollectionBusy:
                pass
        archive = Archive(root / "123")
        try:
            archive.ingest(
                [
                    dict(
                        source="visible",
                        record_key="smoke",
                        source_id="smoke",
                        content="离线验证",
                        photos=[],
                        published_at="2020-01-01T00:00:00+00:00",
                    )
                ]
            )
            target = export_archive(archive, root / "export")
            assert (target / "index.html").is_file()
        finally:
            archive.close()
        data = io.BytesIO()
        Image.new("RGB", (2, 2)).save(data, "PNG")
        assert Image.open(io.BytesIO(data.getvalue())).size == (2, 2)
        Path(destination).write_text(
            json.dumps(
                dict(
                    ok=True,
                    **release_info(),
                    architecture=platform.machine(),
                    platform=platform.system(),
                )
            ),
            encoding="utf-8",
        )
