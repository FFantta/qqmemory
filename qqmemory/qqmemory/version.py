"""Shared release identity for desktop packages and the cloud service."""

import json
import os
from pathlib import Path

VERSION = "0.5.3"
BUILD = "11"


def release_info():
    packaged = Path(__file__).with_name("build-info.json")
    if packaged.is_file():
        return json.loads(packaged.read_text(encoding="utf-8"))
    return {
        "version": VERSION,
        "build": BUILD,
        "source_revision": os.environ.get("RENDER_GIT_COMMIT"),
    }
