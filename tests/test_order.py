import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.bom import Bom, PlanItem
from renglo_dev.heal import editable_target, install_order
from renglo_dev.launch import _scripts
from renglo_dev.platform import is_windows, venv_renglo_serve


class OrderTests(unittest.TestCase):
    def test_core_first_then_extensions_and_white_label(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self._project(workspace / "dev" / "renglo-lib")
            self._project(workspace / "dev" / "renglo-api")
            self._project(workspace / "dev" / "acme-wl")
            self._project(workspace / "dev" / "wss")
            self._project(workspace / "extensions" / "zeta" / "package")
            self._project(workspace / "extensions" / "alpha")
            bom = Bom(
                name="example",
                region="us-east-1",
                wl_npm="@acme/wl",
                items=[
                    PlanItem("renglo-lib", "renglo/renglo-lib", "dev/renglo-lib", True),
                    PlanItem("zeta", "acme/zeta", "extensions/zeta", True),
                ],
            )
            order = [path.name for path in install_order(workspace, bom)]
            self.assertEqual(order, ["renglo-lib", "renglo-api", "zeta", "alpha", "acme-wl"])
            self.assertIsNone(editable_target(workspace / "dev" / "empty"))

    def test_start_scripts_are_valid(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "renglo-dev"
            serve = venv_renglo_serve(root / "venv")
            serve.parent.mkdir(parents=True, exist_ok=True)
            serve.write_text("", encoding="utf-8")
            api = workspace / "dev" / "renglo-api"
            api.mkdir(parents=True)
            config = api / "env_config.py"
            config.write_text("SECRET_KEY = 'x'\n", encoding="utf-8")
            console = workspace / "console"
            (console / "node_modules").mkdir(parents=True)
            (console / "package.json").write_text("{}\n", encoding="utf-8")
            from renglo_dev import launch

            original = launch._port_open
            launch._port_open = lambda _port: False
            try:
                scripts = _scripts(
                    workspace,
                    root,
                    {"emulators": {}},
                    "dev-admin",
                    "us-east-1",
                    str(config),
                )
            finally:
                launch._port_open = original
            self.assertEqual([item[0] for item in scripts], ["renglo-api", "renglo-console"])
            for title, script, _port in scripts:
                text = script.read_text(encoding="utf-8")
                if is_windows():
                    self.assertTrue(script.suffix.lower() == ".ps1", text)
                    if title == "renglo-api":
                        self.assertIn("renglo-serve", text.lower())
                else:
                    result = subprocess.run(["bash", "-n", str(script)], check=False)
                    self.assertEqual(result.returncode, 0, text)

    def _project(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if path.name == "package":
            (path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        else:
            (path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
