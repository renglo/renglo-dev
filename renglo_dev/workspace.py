"""Workspace root, saved answers, and BOM location."""

from __future__ import annotations

import re
from pathlib import Path

from renglo_dev.bom import normalize_bom_spec


STATE_NAME = ".renglo-dev.yaml"
LAUNCHER_NAME = ".env.launcher"

HOME_MESSAGE = """\
renglo-dev is sitting in your home directory. The folder that contains it is
the workspace, and that must be a project folder.

  mkdir my-app
  cd my-app
  git clone https://github.com/renglo/renglo-dev.git
  ./renglo-dev/renglo

On Windows, from the same folder:

  .\\renglo-dev\\renglo.ps1
"""


class WorkspaceError(Exception):
    pass


def renglo_dev_root() -> Path:
    return Path(__file__).resolve().parents[1]


def workspace_of(root: Path) -> Path:
    workspace = root.resolve().parent
    if workspace == Path.home().resolve():
        raise WorkspaceError(HOME_MESSAGE.rstrip())
    return workspace


def state_path(root: Path) -> Path:
    return root / STATE_NAME


def launcher_path(root: Path) -> Path:
    return root / LAUNCHER_NAME


def load_state(root: Path) -> dict:
    path = state_path(root)
    if not path.is_file():
        return {}
    data: dict = {}
    emulators: dict[str, bool] | None = None
    in_emulators = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if in_emulators and line.startswith((" ", "\t")):
            key, value = _split(line.strip())
            assert emulators is not None
            emulators[key] = value.lower() == "true"
            continue
        if ":" not in line:
            continue
        key, value = _split(line.strip())
        if key == "emulators" and value == "":
            emulators = {}
            in_emulators = True
            continue
        in_emulators = False
        data[key] = value
    if emulators is not None:
        data["emulators"] = emulators
    return data


def save_state(root: Path, state: dict) -> None:
    lines = [
        f"bom: {_scalar(str(state.get('bom', '')))}",
        f"aws_profile: {_scalar(str(state.get('aws_profile', '')))}",
        f"aws_region: {_scalar(str(state.get('aws_region', '')))}",
        "emulators:",
    ]
    emulators = state.get("emulators") or {}
    for key in emulators:
        flag = "true" if emulators[key] else "false"
        lines.append(f"  {key}: {flag}")
    lines.append("")
    state_path(root).write_text("\n".join(lines), encoding="utf-8")


def resolve_bom(workspace: Path, spec: str) -> tuple[Path, str | None]:
    """Return the checkout path and, when it still needs cloning, owner/repo."""
    text = normalize_bom_spec(spec)
    candidate = Path(text).expanduser()
    if candidate.is_file() and candidate.name == "renglo.yaml":
        candidate = candidate.parent
    if not candidate.is_absolute():
        relative = (workspace / candidate).resolve()
        if relative.exists():
            candidate = relative
    if candidate.exists():
        return candidate.resolve(), None
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        name = text.split("/", 1)[1]
        return workspace / "ops" / name, text
    raise WorkspaceError(
        "BOM must be a GitHub owner/repo, a GitHub URL, or a path to a checkout that contains renglo.yaml.\n"
        f"  Got: {spec}"
    )


def read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = _unquote(value.strip())
    return data


def display(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _split(text: str) -> tuple[str, str]:
    key, value = text.split(":", 1)
    return key.strip(), _unquote(value.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        if value[0] == "'":
            inner = inner.replace("''", "'")
        return inner
    return value


def _scalar(value: str) -> str:
    if value == "" or re.search(r"[:#\s'\"]", value):
        return "'" + value.replace("'", "''") + "'"
    return value
