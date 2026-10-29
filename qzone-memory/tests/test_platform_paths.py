import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qzone_memory.mac_app import data_root
from qzone_memory.trial import TrialLimits


class PlatformTests(unittest.TestCase):
    def test_windows_data_directory_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as root, patch('qzone_memory.mac_app.__file__',str(Path('/missing')/'mac_app.py')):
            with patch('qzone_memory.mac_app.sys.platform','win32'), patch.dict(os.environ,{'LOCALAPPDATA':root},clear=True):
                self.assertEqual(data_root(),Path(root)/'SpaceMemory')
            with patch.dict(os.environ,{'SPACE_MEMORY_DATA_DIR':root},clear=True):
                self.assertEqual(data_root(),Path(root).resolve())

    def test_limits_require_positive_values_and_valid_deadlines(self):
        with self.assertRaises(ValueError):
            TrialLimits(scan_seconds=10,total_seconds=1)
        with self.assertRaises(ValueError):
            TrialLimits(media=0)
