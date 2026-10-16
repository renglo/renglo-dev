"""OS-specific paths and launcher entrypoints for renglo-dev."""

from __future__ import annotations

import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def venv_python(venv: Path) -> Path:
    if is_windows():
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_renglo_serve(venv: Path) -> Path:
    if is_windows():
        exe = venv / "Scripts" / "renglo-serve.exe"
        if exe.is_file():
            return exe
        return venv / "Scripts" / "renglo-serve"
    return venv / "bin" / "renglo-serve"


def venv_ready(venv: Path) -> bool:
    return venv_python(venv).is_file()


def pip_conf_path(venv: Path) -> Path:
    return venv / "pip.conf"


def patch_venv_pip_config(venv: Path) -> None:
    """Point this venv at renglo-dev/pip.conf (PyPI only) when activated."""
    marker = "# renglo-dev: use PyPI while this venv is active"
    conf = pip_conf_path(venv)
    conf.write_text(f"[global]\nindex-url = https://pypi.org/simple\n", encoding="utf-8")

    if is_windows():
        activate_bat = venv / "Scripts" / "activate.bat"
        if activate_bat.is_file():
            text = activate_bat.read_text(encoding="utf-8")
            if marker not in text:
                activate_bat.write_text(
                    text.rstrip()
                    + f"\r\n{marker}\r\nset PIP_CONFIG_FILE=%VIRTUAL_ENV%\\pip.conf\r\n",
                    encoding="utf-8",
                )
        activate_ps1 = venv / "Scripts" / "Activate.ps1"
        if activate_ps1.is_file():
            text = activate_ps1.read_text(encoding="utf-8")
            if marker not in text:
                activate_ps1.write_text(
                    text.rstrip()
                    + f"\n\n{marker}\n$env:PIP_CONFIG_FILE = \"$env:VIRTUAL_ENV\\pip.conf\"\n",
                    encoding="utf-8",
                )
        return

    activate = venv / "bin" / "activate"
    if activate.is_file():
        text = activate.read_text(encoding="utf-8")
        if marker not in text:
            activate.write_text(
                text.rstrip() + f"\n\n{marker}\nexport PIP_CONFIG_FILE=\"$VIRTUAL_ENV/pip.conf\"\n",
                encoding="utf-8",
            )


def editable_dist_info_glob(venv: Path):
    if is_windows():
        return venv.glob("Lib/site-packages/*.dist-info/direct_url.json")
    return venv.glob("lib/python*/site-packages/*.dist-info/direct_url.json")


def launcher_command(root: Path) -> str:
    if is_windows():
        return r".\renglo-dev\renglo.ps1"
    return "./renglo-dev/renglo"


def bash_for_emulators() -> str | None:
    import shutil

    return shutil.which("bash")
