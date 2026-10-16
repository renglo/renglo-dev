"""Start the API, the console, and any emulators the developer turned on."""

from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from renglo_dev.heal import load_emulators
from renglo_dev.platform import bash_for_emulators, is_windows, venv_renglo_serve
from renglo_dev.workspace import display, launcher_path, read_env_file


API_PORT = 5001
CONSOLE_PORT = 5174


def launch(workspace: Path, root: Path, state: dict, *, here: bool) -> int:
    profile, region, config_path = launch_env(root, state)
    scripts = _scripts(workspace, root, state, profile, region, config_path)
    if not scripts:
        print("Nothing to start.")
        return 1
    if here or sys.platform != "darwin":
        if not here and sys.platform != "darwin":
            print("This machine is not macOS, so processes stay in this terminal.")
            print("On a Mac, the same command opens one Terminal window per process.")
        return _run_here(scripts)
    return _open_terminals(workspace, scripts)


def launch_env(root: Path, state: dict) -> tuple[str, str, str]:
    file_env = read_env_file(launcher_path(root))
    profile = file_env.get("AWS_PROFILE") or str(state.get("aws_profile") or "")
    region = file_env.get("AWS_DEFAULT_REGION") or str(state.get("aws_region") or "")
    config = file_env.get("RENGLO_CONFIG_PATH") or ""
    if not config:
        config = str(root.parent / "dev" / "renglo-api" / "env_config.py")
    return profile, region, config


def _scripts(
    workspace: Path,
    root: Path,
    state: dict,
    profile: str,
    region: str,
    config_path: str,
) -> list[tuple[str, Path, int]]:
    run_dir = root / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    planned: list[tuple[str, Path, int]] = []

    serve = venv_renglo_serve(root / "venv")
    if serve.is_file() and Path(config_path).is_file():
        if is_windows():
            body = _api_ps1(workspace, root, profile, region, config_path, serve)
            planned.append(("renglo-api", _write(run_dir / "api.ps1", body), API_PORT))
        else:
            body = _api_sh(workspace, root, profile, region, config_path)
            planned.append(("renglo-api", _write(run_dir / "api.sh", body), API_PORT))
    else:
        print("API was not started: renglo-dev/venv or dev/renglo-api/env_config.py is missing.")

    console = workspace / "console"
    if (console / "node_modules").is_dir() and (console / "package.json").is_file():
        if is_windows():
            body = _console_ps1(console)
            planned.append(("renglo-console", _write(run_dir / "console.ps1", body), CONSOLE_PORT))
        else:
            body = _console_sh(console)
            planned.append(("renglo-console", _write(run_dir / "console.sh", body), CONSOLE_PORT))
    else:
        print("Console was not started: run ./renglo install after console/ is cloned.")

    chosen = state.get("emulators") or {}
    for emulator in load_emulators(root):
        identity = emulator.get("id", "")
        if not chosen.get(identity):
            continue
        dest = workspace / emulator.get("dest", "")
        if not (dest / ".git").is_dir():
            print(f"{identity} was not started: {emulator.get('dest', dest)} is not cloned.")
            continue
        venv_name = emulator.get("venv", "")
        if venv_name and not (dest / venv_name).is_dir():
            print(f"{identity} was not started: {venv_name} is missing in {display(workspace, dest)}.")
            continue
        start = emulator.get("start", "").strip()
        if not start:
            print(f"{identity} was not started: emulators.yaml has no start command.")
            continue
        port = int(emulator.get("port") or "0")
        url = emulator.get("url") or ""
        if is_windows():
            body = _emulator_ps1(dest, identity, url, profile, region, config_path, start)
            planned.append((f"renglo-{identity}", _write(run_dir / f"{identity}.ps1", body), port))
        else:
            body = _emulator_sh(dest, identity, url, profile, region, config_path, start)
            planned.append((f"renglo-{identity}", _write(run_dir / f"{identity}.sh", body), port))

    ready = []
    for title, script, port in planned:
        if port and _port_open(port):
            print(f"{title} is already listening on 127.0.0.1:{port}")
            continue
        ready.append((title, script, port))
    return ready


def _api_sh(workspace: Path, root: Path, profile: str, region: str, config_path: str) -> str:
    return "\n".join(
        [
            "#!/bin/bash",
            "set -uo pipefail",
            f"export AWS_PROFILE={_sh(profile)}",
            f"export AWS_DEFAULT_REGION={_sh(region)}",
            f"export RENGLO_CONFIG_PATH={_sh(config_path)}",
            f"cd {_sh(str(workspace / 'dev' / 'renglo-api'))} || exit 1",
            f"source {_sh(str(root / 'venv' / 'bin' / 'activate'))} || exit 1",
            'echo "API  http://127.0.0.1:5001"',
            "renglo-serve --host 127.0.0.1 --port 5001 --debug",
            "status=$?",
            _keep_open_sh(),
            "exit $status",
            "",
        ]
    )


def _api_ps1(workspace: Path, root: Path, profile: str, region: str, config_path: str, serve: Path) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$env:AWS_PROFILE = {_ps(profile)}",
            f"$env:AWS_DEFAULT_REGION = {_ps(region)}",
            f"$env:RENGLO_CONFIG_PATH = {_ps(config_path)}",
            f"Set-Location {_ps(str(workspace / 'dev' / 'renglo-api'))}",
            'Write-Host "API  http://127.0.0.1:5001"',
            f"& {_ps(str(serve))} --host 127.0.0.1 --port 5001 --debug",
            "exit $LASTEXITCODE",
            "",
        ]
    )


def _console_sh(console: Path) -> str:
    return "\n".join(
        [
            "#!/bin/bash",
            "set -uo pipefail",
            f"cd {_sh(str(console))} || exit 1",
            'echo "Console  http://127.0.0.1:5174"',
            "npm run dev",
            "status=$?",
            _keep_open_sh(),
            "exit $status",
            "",
        ]
    )


def _console_ps1(console: Path) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"Set-Location {_ps(str(console))}",
            'Write-Host "Console  http://127.0.0.1:5174"',
            "npm run dev",
            "exit $LASTEXITCODE",
            "",
        ]
    )


def _emulator_sh(
    dest: Path, identity: str, url: str, profile: str, region: str, config_path: str, start: str
) -> str:
    return "\n".join(
        [
            "#!/bin/bash",
            "set -uo pipefail",
            f"export AWS_PROFILE={_sh(profile)}",
            f"export AWS_DEFAULT_REGION={_sh(region)}",
            f"export RENGLO_CONFIG_PATH={_sh(config_path)}",
            "export LOCAL_API_BASE=${LOCAL_API_BASE:-http://127.0.0.1:5001}",
            f"cd {_sh(str(dest))} || exit 1",
            f'echo "{identity}  {url}"',
            start,
            "status=$?",
            _keep_open_sh(),
            "exit $status",
            "",
        ]
    )


def _emulator_ps1(
    dest: Path, identity: str, url: str, profile: str, region: str, config_path: str, start: str
) -> str:
    bash = bash_for_emulators()
    if not bash:
        return "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f'Write-Error "Git Bash (bash on PATH) is required to start emulator {identity}."',
                "exit 1",
                "",
            ]
        )
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$env:AWS_PROFILE = {_ps(profile)}",
            f"$env:AWS_DEFAULT_REGION = {_ps(region)}",
            f"$env:RENGLO_CONFIG_PATH = {_ps(config_path)}",
            '$env:LOCAL_API_BASE = if ($env:LOCAL_API_BASE) { $env:LOCAL_API_BASE } else { "http://127.0.0.1:5001" }',
            f"Set-Location {_ps(str(dest))}",
            f'Write-Host "{identity}  {url}"',
            f"& {_ps(bash)} -lc {_ps(start)}",
            "exit $LASTEXITCODE",
            "",
        ]
    )


def _run_here(scripts: list[tuple[str, Path, int]]) -> int:
    print()
    print("Ctrl+C stops every process started in this terminal.")
    print()
    processes: list[subprocess.Popen] = []

    def stop(*_args) -> None:
        for process in processes:
            if process.poll() is None:
                if is_windows():
                    process.terminate()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    env = os.environ.copy()
    env.pop("RENGLO_KEEP_OPEN", None)
    for _title, script, _port in scripts:
        processes.append(_popen_script(script, env))
    exit_code = 0
    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    exit_code = code
                    stop()
                    return exit_code
            time.sleep(0.4)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if is_windows():
                    process.kill()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    return exit_code


def _popen_script(script: Path, env: dict[str, str]) -> subprocess.Popen:
    if script.suffix.lower() == ".ps1":
        return subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if is_windows() else 0,
        )
    return subprocess.Popen(
        ["bash", str(script)],
        start_new_session=not is_windows(),
        env=env,
    )


def _open_terminals(workspace: Path, scripts: list[tuple[str, Path, int]]) -> int:
    opened = 0
    for title, script, _port in scripts:
        command = run_dir_command(script)
        if _open_terminal(command):
            print(f"opened   {title}")
            opened += 1
        else:
            print(f"Could not open a terminal for {title}.")
            print(f"  bash {shlex.quote(str(script))}")
    print()
    if opened:
        print(f"Started {opened} Terminal window(s). Close a window, or press Ctrl+C in it, to stop that process.")
        print(f"Workspace: {workspace}")
        return 0
    print("No Terminal windows were opened. Re-run with --here to stay in this terminal.")
    return 1


def run_dir_command(script: Path) -> Path:
    """Write a .command wrapper that keeps the window open after the process exits."""
    wrapper = script.with_suffix(".command")
    wrapper.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "export RENGLO_KEEP_OPEN=1",
                f"bash {_sh(str(script))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    script.chmod(0o755)
    return wrapper


def _open_terminal(command: Path) -> bool:
    result = subprocess.run(["open", "-a", "Terminal", str(command)])
    return result.returncode == 0


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    if not is_windows():
        path.chmod(0o755)
    return path


def _keep_open_sh() -> str:
    return "\n".join(
        [
            'if [[ "${RENGLO_KEEP_OPEN:-}" == "1" ]]; then',
            '  echo',
            '  echo "Exited with status $status. Press return to close this window."',
            "  read -r _",
            "fi",
        ]
    )


def _sh(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
