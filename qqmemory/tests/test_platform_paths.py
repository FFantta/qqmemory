import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qqmemory.mac_app import data_root
from qqmemory.trial import TrialLimits


class PlatformTests(unittest.TestCase):
    def test_windows_data_directory_and_explicit_override(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch("qqmemory.mac_app.__file__", str(Path("/missing") / "mac_app.py")),
        ):
            with (
                patch("qqmemory.mac_app.sys.platform", "win32"),
                patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=True),
            ):
                self.assertEqual(data_root(), Path(root) / "qqmemory")
            with patch.dict(os.environ, {"SPACE_MEMORY_DATA_DIR": root}, clear=True):
                self.assertEqual(data_root(), Path(root).resolve())

    def test_new_configuration_wins_and_existing_archive_is_not_lost(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch("qqmemory.mac_app.__file__", str(Path("/missing") / "mac_app.py")),
        ):
            with patch.dict(
                os.environ,
                {"QQMEMORY_DATA_DIR": root, "SPACE_MEMORY_DATA_DIR": "/wrong"},
                clear=True,
            ):
                self.assertEqual(data_root(), Path(root).resolve())
            with (
                patch("qqmemory.mac_app.sys.platform", "win32"),
                patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=True),
            ):
                legacy = Path(root) / "SpaceMemory"
                legacy.mkdir()
                self.assertEqual(data_root(), legacy)
                canonical = Path(root) / "qqmemory"
                canonical.mkdir()
                self.assertEqual(data_root(), canonical)

    def test_limits_require_positive_values_and_valid_deadlines(self):
        with self.assertRaises(ValueError):
            TrialLimits(scan_seconds=10, total_seconds=1)
        with self.assertRaises(ValueError):
            TrialLimits(media=0)
