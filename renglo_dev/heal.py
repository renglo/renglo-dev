"""Clone what is missing and install what is not already installed."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from renglo_dev.bom import BRANCH, Bom, core_items, parse_bom, parse_manifest
from renglo_dev.configgen import (
    BACKEND_PLACEHOLDERS,
    CONSOLE_PLACEHOLDERS,
    ConfigReport,
    ensure_local_config,
    placeholder_keys,
)
from renglo_dev.platform import (
    bash_for_emulators,
    editable_dist_info_glob,
    is_windows,
    launcher_command,
    patch_venv_pip_config,
    venv_python,
    venv_ready,
)
from renglo_dev.workspace import display, resolve_bom


PYPI_INDEX = "https://pypi.org/simple"
NPM_REGISTRY = "https://registry.npmjs.org"

CORE_DESTS = tuple(item.dest for item in core_items())


def prerequisites() -> list[str]:
    missing = []
    if sys.version_info < (3, 12):
        missing.append("python3.12 (this script is running on an older Python)")
    if shutil.which("python3.12") is None and sys.version_info < (3, 12):
        if is_windows() and shutil.which("py") is None:
            missing.append("python3.12 or py (Python launcher) on PATH")
        elif not is_windows():
            missing.append("python3.12 on PATH")
    for command in ("git", "node", "npm", "aws"):
        if shutil.which(command) is None:
            missing.append(command)
    if not _github_access():
        missing.append("GitHub access via `gh auth login`, or an SSH key that can clone git@github.com")
    return missing


def print_prerequisites(missing: list[str]) -> None:
    print("Install these and run the command again:")
    for item in missing:
        print(f"  - {item}")


def heal(workspace: Path, root: Path, state: dict, *, refresh: bool) -> tuple[list[str], ConfigReport | None]:
    """Bring the workspace up to the BOM. Returns errors and the config report."""
    errors: list[str] = []
    spec = str(state.get("bom", "")).strip()
    if not spec:
        return [f"No BOM is saved. Run {launcher_command(root)} again and answer the prompt."], None
    try:
        checkout, github = resolve_bom(workspace, spec)
    except Exception as exc:
        return [str(exc)], None

    if github and not (checkout / "renglo.yaml").is_file():
        status = clone_repo(workspace, github, checkout, BRANCH)
        if status not in ("present", "cloned"):
            errors.append(f"Could not clone BOM {github} into {display(workspace, checkout)}")
            return errors, None
    if not (checkout / "renglo.yaml").is_file():
        errors.append(f"No renglo.yaml in {checkout}")
        return errors, None

    print(f"bom      {display(workspace, checkout)}")
    bom = parse_bom((checkout / "renglo.yaml").read_text(encoding="utf-8"))
    errors.extend(bom.errors)
    if not str(state.get("aws_region") or "").strip() and bom.region:
        state["aws_region"] = bom.region

    for item in bom.items:
        status = clone_repo(workspace, item.repo, workspace / item.dest, BRANCH)
        if status not in ("present", "cloned"):
            errors.append(f"Could not clone {item.repo} into {item.dest}")

    manifest = load_emulators(root)
    chosen = state.get("emulators") or {}
    if any(chosen.get(item.get("id", "")) for item in manifest):
        ensure_venv(root)
    for emulator in manifest:
        if not chosen.get(emulator.get("id", "")):
            continue
        dest = workspace / emulator["dest"]
        status = clone_repo(workspace, emulator["repo"], dest, BRANCH)
        if status not in ("present", "cloned"):
            errors.append(f"Could not clone emulator {emulator['id']} ({emulator['repo']})")
            continue
        setup_error = setup_emulator(root, dest, emulator, refresh=refresh)
        if setup_error:
            errors.append(setup_error)

    python_errors = install_python(workspace, root, bom, refresh=refresh)
    errors.extend(python_errors)
    if not install_console(workspace, root, refresh=refresh):
        if (workspace / "console" / "package.json").is_file():
            errors.append("npm install in console/ failed")
        elif not (workspace / "console").is_dir():
            errors.append("console/ is missing")
        else:
            errors.append("console/package.json is missing")

    report = ensure_local_config(
        workspace,
        root,
        wl_name=bom.name,
        wl_npm=bom.wl_npm,
        region=str(state.get("aws_region") or bom.region or ""),
        profile=str(state.get("aws_profile") or ""),
        wss=bool(chosen.get("wss")),
    )
    errors.extend(f"Config file was not written: {path}" for path in report.missing)
    return errors, report


def doctor(workspace: Path, root: Path, state: dict) -> int:
    print(f"Workspace  {workspace}")
    print(f"renglo-dev {root}")
    missing = prerequisites()
    if missing:
        print()
        print_prerequisites(missing)
    else:
        print("Prerequisites  python3.12, git, node, npm, aws, GitHub access")

    spec = str(state.get("bom", "")).strip()
    if not spec:
        print()
        print(f"No BOM saved yet. Run {launcher_command(root)} install and it will ask where the BOM is.")
        return 1

    try:
        checkout, _github = resolve_bom(workspace, spec)
    except Exception as exc:
        print()
        print(exc)
        return 1

    print(f"BOM         {spec}")
    if not (checkout / "renglo.yaml").is_file():
        print(f"renglo.yaml is not in {checkout}")
        return 1

    bom = parse_bom((checkout / "renglo.yaml").read_text(encoding="utf-8"))
    print()
    print("Checkouts  (existing repos stay on their current branch)")
    missing_core = False
    for item in bom.items:
        path = workspace / item.dest
        if (path / ".git").is_dir():
            print(f"  present  {item.dest}  ({_branch(path)})")
        elif path.exists():
            print(f"  blocked  {item.dest}  (remove this path; it is not a git checkout)")
            if item.dest in CORE_DESTS:
                missing_core = True
        else:
            print(f"  missing  {item.dest}  {item.repo}")
            if item.dest in CORE_DESTS:
                missing_core = True
    for error in bom.errors:
        print(f"  bom      {error}")

    print()
    print("Python")
    venv = root / "venv"
    if venv_ready(venv):
        print(f"  venv     {venv}")
        index = editable_index(venv)
        for project in install_order(workspace, bom):
            target = editable_target(project)
            assert target is not None
            rel = display(workspace, project)
            if needs_editable(target, index, refresh=False):
                print(f"  install  {rel}")
            else:
                print(f"  editable {rel}")
    else:
        print("  venv     missing (renglo-dev/venv)")
        missing_core = True

    console = workspace / "console"
    print()
    print("Console")
    if (console / "node_modules").is_dir():
        print("  node_modules  present")
    else:
        print("  node_modules  missing")
        missing_core = True

    print()
    print("Config")
    for label, path, keys in (
        ("env_config.py", workspace / "dev" / "renglo-api" / "env_config.py", BACKEND_PLACEHOLDERS),
        ("console env", workspace / "console" / ".env.development", CONSOLE_PLACEHOLDERS),
    ):
        if not path.is_file():
            print(f"  missing  {path}")
            missing_core = True
            continue
        found = placeholder_keys(path.read_text(encoding="utf-8"), keys)
        if found:
            print(f"  {label}  {path}")
            print(f"    placeholders: {', '.join(found)}")
        else:
            print(f"  {label}  {path}")
    launcher = root / ".env.launcher"
    if launcher.is_file():
        print(f"  launcher  {launcher}")
    else:
        print(f"  launcher  missing ({launcher})")

    print()
    print("Emulators")
    chosen = state.get("emulators")
    manifest = load_emulators(root)
    if chosen is None:
        print("  not chosen yet")
    else:
        for emulator in manifest:
            enabled = "on" if chosen.get(emulator["id"]) else "off"
            dest = workspace / emulator["dest"]
            cloned = "cloned" if (dest / ".git").is_dir() else "not cloned"
            print(f"  {emulator['id']:<8} {enabled:<4} {cloned}  {emulator.get('url', '')}")

    print()
    print("New clones use the develop branch. Later runs leave each repo on its current branch.")
    if missing or missing_core or bom.errors:
        return 1
    return 0


def load_emulators(root: Path) -> list[dict[str, str]]:
    path = root / "emulators.yaml"
    if not path.is_file():
        return []
    return parse_manifest(path.read_text(encoding="utf-8"))


def clone_repo(workspace: Path, repo: str, dest: Path, branch: str) -> str:
    rel = display(workspace, dest)
    git_dir = dest / ".git"
    if git_dir.is_dir():
        print(f"present  {rel}")
        return "present"
    if dest.exists() and not dest.is_dir():
        print(f"blocked  {rel} exists and is not a directory")
        return "blocked"
    if dest.is_dir() and any(dest.iterdir()):
        print(f"blocked  {rel} exists and is not a git checkout")
        return "blocked"
    if dest.is_dir():
        dest.rmdir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    if _gh_authenticated():
        command = ["gh", "repo", "clone", repo, str(dest), "--", "--branch", branch, "--single-branch"]
    else:
        command = [
            "git",
            "clone",
            "--branch",
            branch,
            "--single-branch",
            f"git@github.com:{repo}.git",
            str(dest),
        ]
    print(f"clone    {repo} -> {rel} ({branch})")
    result = subprocess.run(command, env=env)
    if result.returncode != 0 or not git_dir.is_dir():
        print(f"failed   {repo}")
        return "failed"
    return "cloned"


def install_order(workspace: Path, bom: Bom) -> list[Path]:
    selected: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if not path.exists():
            return
        resolved = path.resolve()
        if resolved in seen or editable_target(path) is None:
            return
        seen.add(resolved)
        selected.append(path)

    for rel in ("dev/renglo-lib", "dev/renglo-api"):
        add(workspace / rel)
    for item in bom.items:
        if item.python:
            add(workspace / item.dest)
    extensions = workspace / "extensions"
    if extensions.is_dir():
        for child in sorted(path for path in extensions.iterdir() if path.is_dir()):
            add(child)
    dev = workspace / "dev"
    if dev.is_dir():
        for child in sorted(path for path in dev.iterdir() if path.is_dir() and path.name.endswith("-wl")):
            add(child)
    return selected


def editable_target(path: Path) -> Path | None:
    package = path / "package" / "pyproject.toml"
    if package.is_file():
        return package.parent
    if (path / "pyproject.toml").is_file() or (path / "setup.py").is_file():
        return path
    return None


def editable_index(venv: Path) -> dict[Path, Path]:
    found: dict[Path, Path] = {}
    for direct in editable_dist_info_glob(venv):
        try:
            data = json.loads(direct.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not (data.get("dir_info") or {}).get("editable"):
            continue
        url = data.get("url") or ""
        if not url.startswith("file:"):
            continue
        location = Path(unquote(urlparse(url).path))
        found[location.resolve()] = direct
    return found


def needs_editable(target: Path, index: dict[Path, Path], *, refresh: bool) -> bool:
    if refresh:
        return True
    marker = index.get(target.resolve())
    if marker is None:
        return True
    newest = target / "pyproject.toml"
    if not newest.is_file():
        newest = target / "setup.py"
    if newest.is_file() and newest.stat().st_mtime > marker.stat().st_mtime:
        return True
    return False


def install_python(workspace: Path, root: Path, bom: Bom, *, refresh: bool) -> list[str]:
    errors: list[str] = []
    projects = install_order(workspace, bom)
    requirements = workspace / "dev" / "renglo-api" / "requirements.txt"
    if not projects and not requirements.is_file():
        errors.append("No local Python projects were found, so the venv was not built")
        return errors
    if not (workspace / "dev" / "renglo-api").is_dir():
        errors.append("dev/renglo-api is missing, so the API was not installed")
    venv = ensure_venv(root)
    env = _pypi_env(root)
    python = venv_python(venv)
    stamp_dir = root / ".run"
    stamp_dir.mkdir(parents=True, exist_ok=True)
    pip_stamp = stamp_dir / "pip-upgraded"
    if refresh or not pip_stamp.is_file():
        print("pip      upgrade")
        if _run([str(python), "-m", "pip", "install", "--upgrade", "pip", "--index-url", PYPI_INDEX], env=env) != 0:
            errors.append("pip upgrade failed")
        else:
            pip_stamp.write_text("ok\n", encoding="utf-8")

    req_stamp = stamp_dir / "requirements.sha256"
    index = editable_index(venv)
    failed: list[Path] = []
    lib = [project for project in projects if project.name == "renglo-lib"]
    rest = [project for project in projects if project.name != "renglo-lib"]
    _install_editables(lib, failed, index, python, env, workspace, refresh=refresh)
    if requirements.is_file() and (refresh or not _stamp_matches(req_stamp, requirements)):
        print("pip      renglo-api/requirements.txt")
        code = _run(
            [str(python), "-m", "pip", "install", "--index-url", PYPI_INDEX, "-r", str(requirements)],
            env=env,
            cwd=requirements.parent,
        )
        if code != 0:
            errors.append("pip install -r dev/renglo-api/requirements.txt failed")
        else:
            _write_stamp(req_stamp, requirements)

    index = editable_index(venv)
    _install_editables(rest, failed, index, python, env, workspace, refresh=refresh)
    _retry_editables(failed, python, env, workspace, errors)
    return errors


def _install_editables(projects, failed, index, python, env, workspace, *, refresh: bool) -> None:
    for project in projects:
        target = editable_target(project)
        assert target is not None
        rel = display(workspace, target)
        if not needs_editable(target, index, refresh=refresh):
            print(f"editable {display(workspace, project)}")
            continue
        print(f"pip      -e {rel}")
        if _pip_editable(python, target, env) != 0:
            failed.append(project)


def _retry_editables(failed, python, env, workspace, errors: list[str]) -> None:
    for project in failed:
        target = editable_target(project)
        assert target is not None
        print(f"retry    -e {display(workspace, target)}")
        if _pip_editable(python, target, env) != 0:
            errors.append(f"pip install -e {display(workspace, target)} failed")


def install_console(workspace: Path, root: Path, *, refresh: bool) -> bool:
    console = workspace / "console"
    package = console / "package.json"
    if not package.is_file():
        return False
    source = console / "package-lock.json"
    if not source.is_file():
        source = package
    stamp = root / ".run" / "npm.sha256"
    if (console / "node_modules").is_dir() and not refresh and _stamp_matches(stamp, source):
        print("npm      console (up to date)")
        return True
    print("npm      console")
    env = os.environ.copy()
    env["npm_config_registry"] = NPM_REGISTRY
    code = _run(["npm", "install", "--registry", NPM_REGISTRY], env=env, cwd=console)
    if code != 0:
        return False
    _write_stamp(stamp, source)
    return True


def ensure_venv(root: Path) -> Path:
    venv = root / "venv"
    python = venv_python(venv)
    if not python.is_file():
        print(f"venv     {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    patch_venv_pip_config(venv)
    return venv


def setup_emulator(root: Path, dest: Path, emulator: dict[str, str], *, refresh: bool) -> str | None:
    venv_name = emulator.get("venv", "")
    venv_dir = dest / venv_name if venv_name else None
    setup = emulator.get("setup", "")
    if not setup:
        return None
    setup_path = dest / setup.removeprefix("./")
    if venv_dir is not None and venv_dir.is_dir() and not refresh:
        return None
    if not setup_path.is_file():
        return f"{emulator.get('id', dest.name)}: setup script {setup} is missing"
    print(f"setup    {emulator.get('id', dest.name)}")
    env = _pypi_env(root)
    if is_windows():
        bash = bash_for_emulators()
        if not bash:
            return f"{emulator.get('id', dest.name)}: Git Bash (bash on PATH) is required for {setup}"
        code = _run([bash, str(setup_path)], env=env, cwd=dest)
    else:
        code = _run(["bash", str(setup_path)], env=env, cwd=dest)
    if code != 0:
        return f"{emulator.get('id', dest.name)}: {setup} failed"
    return None


def _pip_editable(python: Path, target: Path, env: dict[str, str]) -> int:
    return _run(
        [str(python), "-m", "pip", "install", "--index-url", PYPI_INDEX, "-e", str(target)],
        env=env,
    )


def _pypi_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PIP_CONFIG_FILE"] = str(root / "venv" / "pip.conf")
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _run(command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> int:
    result = subprocess.run(command, env=env, cwd=cwd)
    return result.returncode


def _stamp_matches(stamp: Path, source: Path) -> bool:
    if not stamp.is_file() or not source.is_file():
        return False
    return stamp.read_text(encoding="utf-8").strip() == _digest(source)


def _write_stamp(stamp: Path, source: Path) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(_digest(source) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _branch(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def _github_access() -> bool:
    return _gh_authenticated() or _ssh_key_present()


def _gh_authenticated() -> bool:
    if shutil.which("gh") is None:
        return False
    result = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _ssh_key_present() -> bool:
    ssh = Path.home() / ".ssh"
    if not ssh.is_dir():
        return False
    names = ("id_ed25519", "id_rsa", "id_ecdsa", "id_ed25519_sk")
    return any((ssh / name).is_file() for name in names)
