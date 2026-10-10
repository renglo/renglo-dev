import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.heal import heal


BOM = """
name: example
accounts:
  staging:
    region: eu-west-1
packages:
  renglo-lib:
    python: renglo-lib
"""


class HealTests(unittest.TestCase):
    def test_existing_branch_and_config_are_left_alone(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "renglo-dev"
            root.mkdir()
            bom = workspace / "ops" / "example-bom"
            bom.mkdir(parents=True)
            (bom / "renglo.yaml").write_text(BOM, encoding="utf-8")

            lib = workspace / "dev" / "renglo-lib"
            lib.mkdir(parents=True)
            head = lib / ".git" / "HEAD"
            head.parent.mkdir()
            head.write_text("ref: refs/heads/feature/stay\n", encoding="utf-8")
            (workspace / "dev" / "renglo-api").mkdir()
            (workspace / "console").mkdir()

            state = {
                "bom": str(bom),
                "aws_profile": "dev-admin",
                "aws_region": "us-east-1",
                "emulators": {"wss": False, "webhook": False, "ebe": False},
            }
            errors, report = heal(workspace, root, state, refresh=False)
            self.assertIsNotNone(report)
            config = workspace / "dev" / "renglo-api" / "env_config.py"
            self.assertTrue(config.is_file())
            self.assertTrue((workspace / "console" / ".env.development").is_file())
            self.assertTrue((root / ".env.launcher").is_file())
            self.assertFalse((root / "venv").exists())
            first = config.read_text(encoding="utf-8")
            self.assertEqual(head.read_text(encoding="utf-8"), "ref: refs/heads/feature/stay\n")
            self.assertTrue(any("console/package.json" in error for error in errors))

            _errors_again, report_again = heal(workspace, root, state, refresh=False)
            self.assertEqual(config.read_text(encoding="utf-8"), first)
            self.assertEqual(report_again.wrote, [])
            self.assertEqual(head.read_text(encoding="utf-8"), "ref: refs/heads/feature/stay\n")


if __name__ == "__main__":
    unittest.main()
