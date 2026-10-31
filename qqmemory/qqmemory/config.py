"""Canonical configuration with read-only support for previous environment names."""

import os


def setting(name, default=None):
    return os.environ.get("QQMEMORY_" + name, os.environ.get("SPACE_MEMORY_" + name, default))
