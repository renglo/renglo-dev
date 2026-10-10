import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.workspace import WorkspaceError, load_state, resolve_bom, save_state, workspace_of


class WorkspaceTests(unittest.TestCase):
    def test_home_is_rejected(self):
        with self.assertRaises(WorkspaceError):
            workspace_of(Path.home() / "renglo-dev")

    def test_state_roundtrip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_state(
                root,
                {
                    "bom": "acme/acme-bom",
                    "aws_profile": "dev-admin",
                    "aws_region": "eu-west-1",
                    "emulators": {"wss": True, "webhook": False, "ebe": False},
                },
            )
            loaded = load_state(root)
            self.assertEqual(loaded["bom"], "acme/acme-bom")
            self.assertEqual(loaded["aws_profile"], "dev-admin")
            self.assertEqual(loaded["aws_region"], "eu-west-1")
            self.assertEqual(loaded["emulators"], {"wss": True, "webhook": False, "ebe": False})

    def test_github_spec_clones_under_ops(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            path, github = resolve_bom(workspace, "https://github.com/acme/acme-bom.git")
            self.assertEqual(github, "acme/acme-bom")
            self.assertEqual(path, workspace / "ops" / "acme-bom")

    def test_existing_checkout_is_used_as_is(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bom = workspace / "ops" / "acme-bom"
            bom.mkdir(parents=True)
            (bom / "renglo.yaml").write_text("name: acme\n", encoding="utf-8")
            path, github = resolve_bom(workspace, str(bom))
            self.assertIsNone(github)
            self.assertEqual(path, bom.resolve())


if __name__ == "__main__":
    unittest.main()
