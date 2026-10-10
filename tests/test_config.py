import ast
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renglo_dev.configgen import ensure_local_config, placeholder_keys, render_env_config, BACKEND_PLACEHOLDERS


class ConfigTests(unittest.TestCase):
    def test_generated_env_config_is_python_and_has_secrets(self):
        text = render_env_config(wl_name="example", region="eu-west-1", wss=True)
        ast.parse(text)
        values = _assignments(text)
        self.assertEqual(values["WL_NAME"], "example")
        self.assertEqual(values["AWS_REGION"], "eu-west-1")
        self.assertNotIn(values["SECRET_KEY"], {"", "x"})
        self.assertNotIn(values["CSRF_SESSION_KEY"], {"", "x"})
        self.assertEqual(values["WEBSOCKET_CONNECTIONS"], "http://127.0.0.1:8080/send_to_client")
        placeholders = placeholder_keys(text, BACKEND_PLACEHOLDERS)
        self.assertIn("BASE_URL", placeholders)
        self.assertIn("COGNITO_USERPOOL_ID", placeholders)
        self.assertNotIn("SECRET_KEY", placeholders)
        self.assertNotIn("AWS_REGION", placeholders)

    def test_existing_files_are_kept(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "renglo-dev"
            root.mkdir()
            api = workspace / "dev" / "renglo-api"
            api.mkdir(parents=True)
            console = workspace / "console"
            console.mkdir()
            original = "SECRET_KEY = 'keep-me'\nCSRF_SESSION_KEY = 'keep-csrf'\n"
            (api / "env_config.py").write_text(original, encoding="utf-8")
            (console / ".env.development").write_text("VITE_API_URL='http://127.0.0.1:5001'\n", encoding="utf-8")
            (root / ".env.launcher").write_text("AWS_PROFILE='hand'\n", encoding="utf-8")

            report = ensure_local_config(
                workspace,
                root,
                wl_name="example",
                wl_npm="@acme/wl",
                region="us-east-1",
                profile="other",
                wss=False,
            )
            self.assertEqual((api / "env_config.py").read_text(encoding="utf-8"), original)
            self.assertEqual((root / ".env.launcher").read_text(encoding="utf-8"), "AWS_PROFILE='hand'\n")
            self.assertEqual(report.wrote, [])
            self.assertEqual(len(report.kept), 3)
            self.assertNotIn("SECRET_KEY", report.placeholders[str(api / "env_config.py")])
            self.assertIn("BASE_URL", report.placeholders[str(api / "env_config.py")])


def _assignments(text: str) -> dict[str, str]:
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


if __name__ == "__main__":
    unittest.main()
