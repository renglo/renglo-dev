import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.platform import (
    editable_dist_info_glob,
    launcher_command,
    venv_python,
    venv_renglo_serve,
)


class PlatformTests(unittest.TestCase):
    def test_venv_paths_unix(self):
        venv = Path("/tmp/venv")
        with mock.patch("renglo_dev.platform.is_windows", return_value=False):
            self.assertEqual(venv_python(venv), venv / "bin" / "python")
            self.assertEqual(venv_renglo_serve(venv), venv / "bin" / "renglo-serve")

    def test_venv_paths_windows(self):
        venv = Path("C:/ws/renglo-dev/venv")
        with mock.patch("renglo_dev.platform.is_windows", return_value=True):
            self.assertEqual(venv_python(venv), venv / "Scripts" / "python.exe")
            self.assertEqual(venv_renglo_serve(venv), venv / "Scripts" / "renglo-serve")

    def test_launcher_command(self):
        root = Path("/ws/renglo-dev")
        with mock.patch("renglo_dev.platform.is_windows", return_value=False):
            self.assertEqual(launcher_command(root), "./renglo-dev/renglo")
        with mock.patch("renglo_dev.platform.is_windows", return_value=True):
            self.assertEqual(launcher_command(root), r".\renglo-dev\renglo.ps1")

    def test_editable_glob_windows(self):
        venv = Path("/tmp/venv")
        with mock.patch("renglo_dev.platform.is_windows", return_value=True):
            patterns = list(editable_dist_info_glob(venv))
            self.assertEqual(len(patterns), 0)


if __name__ == "__main__":
    unittest.main()
