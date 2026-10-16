"""Ask once, heal the workspace, and start the local stack."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from renglo_dev import __version__
from renglo_dev.configgen import print_handoff
from renglo_dev.heal import doctor, heal, load_emulators, prerequisites, print_prerequisites
from renglo_dev.launch import launch
from renglo_dev.platform import launcher_command, venv_renglo_serve
from renglo_dev.workspace import (
    WorkspaceError,
    load_state,
    renglo_dev_root,
    save_state,
    workspace_of,
)


REGISTRY_MESSAGE = """\
This version installs every package with git clone on the develop branch.
Installing from the public and private registries is reserved for a later version.
"""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.from_registry:
        print(REGISTRY_MESSAGE.rstrip())
        return 2
    root = renglo_dev_root()
    try:
        workspace = workspace_of(root)
    except WorkspaceError as exc:
        print(exc)
        return 1
    state = load_state(root)
    if args.command == "doctor":
        return doctor(workspace, root, state)

    missing = prerequisites()
    if missing:
        print_prerequisites(missing)
        return 1
    try:
        state = ensure_choices(workspace, root, state)
    except WorkspaceError as exc:
        print(exc)
        return 1
    save_state(root, state)
    errors, report = heal(workspace, root, state, refresh=args.refresh)
    save_state(root, state)
    if report is not None:
        print_handoff(report)
    if errors:
        print("Could not finish:")
        for error in errors:
            print(f"  - {error}")
        print(f"What succeeded is still in place. Run {launcher_command(root)} again to continue.")
    if args.command == "install":
        return 1 if errors else 0
    if not _can_start(workspace, root):
        return 1
    if errors:
        print("Starting what is ready.")
        print()
    return launch(workspace, root, state, here=args.here)


def ensure_choices(workspace: Path, root: Path, state: dict) -> dict:
    bom = str(state.get("bom") or os.environ.get("RENGLO_BOM") or "").strip()
    if not bom:
        bom = _prompt(
            "Where is the BOM?\n"
            "  A GitHub repo (owner/name or URL), or a path to a checkout that contains renglo.yaml."
        )
    if not bom:
        raise WorkspaceError("A BOM location is required.")
    state["bom"] = bom

    profile = str(state.get("aws_profile") or os.environ.get("AWS_PROFILE") or "").strip()
    if not profile:
        profiles = _aws_profiles()
        if len(profiles) == 1:
            profile = profiles[0]
            print(f"AWS profile  {profile}")
        elif len(profiles) > 1:
            profile = _prompt(
                "Which AWS profile should the local API use?\n  " + ", ".join(profiles)
            )
            if profile not in profiles:
                raise WorkspaceError(
                    f"{profile!r} is not an AWS profile on this machine. Profiles: {', '.join(profiles)}"
                )
        else:
            profile = _prompt("AWS profile name (aws configure list-profiles returned none)")
    if not profile:
        raise WorkspaceError("An AWS profile name is required.")
    state["aws_profile"] = profile

    region = str(
        state.get("aws_region")
        or os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_REGION")
        or ""
    ).strip()
    if not region:
        region = _aws_region(profile)
    # An empty region is filled from the BOM after renglo.yaml is read.
    state["aws_region"] = region

    if "emulators" not in state:
        state["emulators"] = _choose_emulators(root)
    return state


def _choose_emulators(root: Path) -> dict[str, bool]:
    manifest = load_emulators(root)
    if not manifest:
        return {}
    print()
    print("Optional emulators. Each one you turn on is cloned, installed, and opened in its own terminal.")
    for emulator in manifest:
        url = emulator.get("url", "")
        print(f"  {emulator['id']:<8} {emulator.get('title', '')}  {url}")
    raw = os.environ.get("RENGLO_EMULATORS")
    if raw is None:
        raw = _prompt("Which emulators? [none, all, or a comma list such as wss,ebe]", default="none")
    choice = (raw or "none").strip().lower()
    ids = [item["id"] for item in manifest]
    if choice in {"none", "no", ""}:
        selected = set()
    elif choice == "all":
        selected = set(ids)
    else:
        selected = {part.strip() for part in choice.split(",") if part.strip()}
        unknown = selected - set(ids)
        if unknown:
            raise WorkspaceError(
                "Unknown emulator(s): " + ", ".join(sorted(unknown)) + ". Known: " + ", ".join(ids)
            )
    return {identity: identity in selected for identity in ids}


def _aws_profiles() -> list[str]:
    result = subprocess.run(
        ["aws", "configure", "list-profiles"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _aws_region(profile: str) -> str:
    result = subprocess.run(
        ["aws", "configure", "get", "region", "--profile", profile],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _prompt(text: str, default: str | None = None) -> str:
    if not sys.stdin.isatty():
        hint = f" Set it before running, or run the launcher in a terminal. ({text.splitlines()[0]})"
        raise WorkspaceError("This step needs an answer and stdin is not a terminal." + hint)
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or (default or "")


def _can_start(workspace: Path, root: Path) -> bool:
    serve = venv_renglo_serve(root / "venv")
    console = workspace / "console" / "node_modules"
    config = workspace / "dev" / "renglo-api" / "env_config.py"
    if serve.is_file() and console.is_dir() and config.is_file():
        return True
    print("The API and console are not both ready, so nothing was started.")
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renglo",
        description=(
            "Install a local Renglo workspace from a BOM, then start it. "
            "With no command, missing clones and packages are installed and the API and console start in separate Terminal windows. "
            "Pass --here to run the API and the console in this terminal, with both logs in one scrollback."
        ),
        epilog=(
            "commands:\n"
            "  renglo              heal, then one Terminal window for the API and one for the console\n"
            "  renglo --here       heal, then API and console together in this terminal (Ctrl+C stops both)\n"
            "  renglo install      heal and stop, do not start the API or the console\n"
            "  renglo doctor       print what is missing; clone, install, and start nothing\n"
            "  renglo --refresh    reinstall Python and npm dependencies, then start\n"
            "  renglo --here --refresh\n"
            "                      reinstall, then run API and console in this terminal\n"
            "  renglo install --refresh\n"
            "                      reinstall and stop"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="up",
        choices=("up", "install", "doctor"),
        help="up starts the stack (the default), install stops after the check, doctor only prints status",
    )
    parser.add_argument(
        "--here",
        action="store_true",
        help="run the API and the console in this terminal; their logs share one scrollback; Ctrl+C stops both",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="reinstall Python and npm dependencies even when they are already installed",
    )
    parser.add_argument(
        "--from-registry",
        action="store_true",
        help="Reserved. This version only clones Git repositories",
    )
    parser.add_argument("--version", action="version", version=f"renglo-dev {__version__}")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
