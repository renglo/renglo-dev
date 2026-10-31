import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.bom import checkout_path, github_repo, normalize_bom_spec, parse_bom, parse_manifest


FIXTURE = """
name: example
accounts:
  staging:
    region: eu-west-1
packages:
  renglo-lib:
    python: renglo-lib
  renglo-api:
    python: renglo-api
  console:
    npm: '@renglo/console'
  acme-wl:
    python: acme-wl
    npm: '@acme/wl'
  data:
    python: renglo-data
    npm: '@renglo/data'
  breakdown:
    python: acme-breakdown
    npm: '@acme/breakdown'
  gro:
    repo: renglo/gro
  mystery:
    python: mystery-lib
"""


class BomTests(unittest.TestCase):
    def test_fixture_paths(self):
        bom = parse_bom(FIXTURE)
        dests = {item.dest: item for item in bom.items}
        self.assertEqual(bom.name, "example")
        self.assertEqual(bom.region, "eu-west-1")
        self.assertEqual(bom.wl_npm, "@acme/wl")
        self.assertEqual(dests["dev/renglo-lib"].repo, "renglo/renglo-lib")
        self.assertTrue(dests["dev/renglo-lib"].python)
        self.assertEqual(dests["dev/renglo-api"].repo, "renglo/renglo-api")
        self.assertEqual(dests["console"].repo, "renglo/console")
        self.assertFalse(dests["console"].python)
        self.assertEqual(dests["dev/acme-wl"].repo, "acme/acme-wl")
        self.assertEqual(dests["extensions/data"].repo, "renglo/data")
        self.assertEqual(dests["extensions/breakdown"].repo, "acme/breakdown")
        self.assertEqual(dests["extensions/gro"].repo, "renglo/gro")
        self.assertFalse(dests["extensions/gro"].python)
        self.assertNotIn("extensions/mystery", dests)
        self.assertTrue(any("mystery" in error for error in bom.errors))
        self.assertTrue(all(not item.dest.startswith("ops/") for item in bom.items))

    def test_empty_packages_still_include_core(self):
        bom = parse_bom("name: liga\npackages: {}\n")
        dests = {item.dest: item for item in bom.items}
        self.assertEqual(list(dests), ["dev/renglo-lib", "dev/renglo-api", "console"])
        self.assertEqual(dests["dev/renglo-lib"].repo, "renglo/renglo-lib")
        self.assertEqual(dests["dev/renglo-api"].repo, "renglo/renglo-api")
        self.assertEqual(dests["console"].repo, "renglo/console")
        self.assertFalse(bom.errors)

    def test_missing_core_is_filled_and_a_fork_is_kept(self):
        bom = parse_bom(
            """
packages:
  renglo-lib:
    repo: acme/renglo-lib
    python: renglo-lib
  data:
    python: renglo-data
    npm: '@renglo/data'
"""
        )
        dests = {item.dest: item.repo for item in bom.items}
        self.assertEqual(
            list(dests),
            ["dev/renglo-lib", "dev/renglo-api", "console", "extensions/data"],
        )
        self.assertEqual(dests["dev/renglo-lib"], "acme/renglo-lib")
        self.assertEqual(dests["dev/renglo-api"], "renglo/renglo-api")
        self.assertEqual(dests["console"], "renglo/console")
        self.assertFalse(bom.errors)

    def test_forked_core_repo_stays_under_dev(self):
        self.assertEqual(checkout_path("acme/renglo-lib", {}), "dev/renglo-lib")
        self.assertEqual(github_repo("data", {"repo": "acme/data", "npm": "@renglo/data"}), "acme/data")

    def test_normalize_github_urls(self):
        self.assertEqual(normalize_bom_spec("https://github.com/acme/acme-bom.git"), "acme/acme-bom")
        self.assertEqual(normalize_bom_spec("git@github.com:acme/acme-bom.git"), "acme/acme-bom")
        self.assertEqual(normalize_bom_spec("/tmp/acme-bom"), "/tmp/acme-bom")

    def test_shipped_manifest(self):
        text = (Path(__file__).resolve().parents[1] / "emulators.yaml").read_text(encoding="utf-8")
        items = parse_manifest(text)
        self.assertEqual([item["id"] for item in items], ["wss", "webhook", "ebe"])
        self.assertEqual(items[0]["repo"], "renglo/wss")
        self.assertIn("dev_ws_service.py", items[0]["start"])

    def test_workspace_bom_when_present(self):
        path = Path(__file__).resolve().parents[2] / "ops" / "skbrk-bom" / "renglo.yaml"
        if not path.is_file():
            self.skipTest("no BOM beside renglo-dev")
        bom = parse_bom(path.read_text(encoding="utf-8"))
        dests = {item.dest: item.repo for item in bom.items}
        self.assertEqual(dests["dev/renglo-lib"], "renglo/renglo-lib")
        self.assertEqual(dests["dev/renglo-api"], "renglo/renglo-api")
        self.assertEqual(dests["console"], "renglo/console")
        self.assertEqual(dests["dev/skbrk-wl"], "skbrk/skbrk-wl")
        self.assertEqual(dests["extensions/data"], "renglo/data")
        self.assertEqual(dests["extensions/breakdown"], "skbrk/breakdown")
        self.assertEqual(dests["extensions/gro"], "renglo/gro")
        self.assertFalse(bom.errors)
        self.assertTrue(bom.region)
        self.assertNotIn("ops/renglo-registry", dests)
        self.assertNotIn("ops/skbrk-registry", dests)


if __name__ == "__main__":
    unittest.main()
