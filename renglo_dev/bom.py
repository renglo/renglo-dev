"""Read a BOM renglo.yaml without a third-party YAML library."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


BRANCH = "develop"

# Always cloned, even when `packages` is empty or omits them.
# A BOM entry for the same folder wins, so a fork stays a fork.
CORE_DEFAULTS: tuple[tuple[str, dict[str, str]], ...] = (
    ("renglo-lib", {"python": "renglo-lib"}),
    ("renglo-api", {"python": "renglo-api"}),
    ("console", {"npm": "@renglo/console"}),
)

_FIELD = re.compile(
    r"^\s+(python|npm|repo)\s*:\s*"
    r"(?:(?P<q>['\"])(?P<quoted>.*)(?P=q)|(?P<bare>\S+))"
    r"\s*(?:#.*)?$"
)
_SLOT = re.compile(r"^(\s+)([^:#\s][^:]*):\s*(?:#.*)?$")
_ROOT = re.compile(
    r"^(?P<key>[A-Za-z0-9_-]+):\s*(?:(?P<q>['\"])(?P<quoted>.*?)(?P=q)|(?P<bare>[^#\s]*))\s*(?:#.*)?$"
)


@dataclass(frozen=True)
class PlanItem:
    handle: str
    repo: str
    dest: str
    python: bool


@dataclass
class Bom:
    name: str
    region: str
    wl_npm: str
    items: list[PlanItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_bom(text: str) -> Bom:
    lines = text.splitlines()
    name = _root_scalar(lines, "name")
    region = _first_region(lines)
    slots, slot_errors = _packages(lines)
    items: list[PlanItem] = []
    errors = list(slot_errors)
    seen: set[str] = set()
    wl_npm = "@tenant/wl"
    for handle, fields in slots:
        npm = fields.get("npm", "")
        if npm.endswith("/wl"):
            wl_npm = npm
        try:
            repo = github_repo(handle, fields)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        dest = checkout_path(repo, fields)
        if dest in seen:
            continue
        seen.add(dest)
        items.append(
            PlanItem(
                handle=handle,
                repo=repo,
                dest=dest,
                python=bool(fields.get("python")),
            )
        )
    items = _with_core(items)
    return Bom(name=name, region=region, wl_npm=wl_npm, items=items, errors=errors)


def core_items() -> list[PlanItem]:
    """The three checkouts every workspace has, using the public renglo repos."""
    items: list[PlanItem] = []
    for handle, fields in CORE_DEFAULTS:
        repo = github_repo(handle, fields)
        items.append(
            PlanItem(
                handle=handle,
                repo=repo,
                dest=checkout_path(repo, fields),
                python=bool(fields.get("python")),
            )
        )
    return items


def github_repo(handle: str, fields: dict[str, str]) -> str:
    repo = fields.get("repo", "").strip()
    if repo:
        return repo
    npm = fields.get("npm", "").strip()
    if npm.startswith("@") and "/" in npm:
        scope, name = npm[1:].split("/", 1)
        if name == "wl":
            return f"{scope}/{scope}-wl"
        return f"{scope}/{name}"
    python_name = fields.get("python", "").strip()
    if python_name in ("renglo-lib", "renglo-api"):
        return f"renglo/{python_name}"
    raise ValueError(
        f"{handle}: set repo: in renglo.yaml so the installer knows which GitHub repo to clone"
    )


def checkout_path(repo: str, fields: dict[str, str]) -> str:
    """Map a GitHub repo onto the workspace folder conventions."""
    name = repo.split("/", 1)[-1]
    npm = fields.get("npm", "")
    if name in ("renglo-api", "renglo-lib"):
        return f"dev/{name}"
    if name == "console" or npm.endswith("/console"):
        return "console"
    if name == "wl" or name.endswith("-wl"):
        folder = name if name.endswith("-wl") else f"{name}-wl"
        return f"dev/{folder}"
    return f"extensions/{name}"


def _with_core(items: list[PlanItem]) -> list[PlanItem]:
    """Keep BOM checkouts, and fill in any of the three core folders that are absent."""
    by_dest = {item.dest: item for item in items}
    cores = [by_dest.get(item.dest, item) for item in core_items()]
    core_dests = {item.dest for item in cores}
    return cores + [item for item in items if item.dest not in core_dests]


def parse_manifest(text: str) -> list[dict[str, str]]:
    """Parse emulators.yaml: a list of maps with scalar fields."""
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw.startswith("- "):
            if current is not None:
                items.append(current)
            current = {}
            rest = raw[2:].strip()
            if rest:
                key, value = _split_field(rest)
                current[key] = value
            continue
        if current is not None and raw.startswith((" ", "\t")):
            key, value = _split_field(stripped)
            current[key] = value
    if current is not None:
        items.append(current)
    return items


def normalize_bom_spec(spec: str) -> str:
    """Accept owner/repo, a git URL, or a filesystem path."""
    text = spec.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[: -len(".git")]
    match = re.search(r"github\.com[:/](?P<repo>[^/]+/[^/]+)$", text)
    if match:
        return match.group("repo")
    return text


def _packages(lines: list[str]) -> tuple[list[tuple[str, dict[str, str]]], list[str]]:
    body = _section(lines, "packages")
    slots: list[tuple[str, dict[str, str]]] = []
    current: str | None = None
    fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal current, fields
        if current:
            slots.append((current, dict(fields)))
        current = None
        fields = {}

    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        field_match = _FIELD.match(line)
        if field_match and current:
            value = field_match.group("quoted")
            if value is None:
                value = field_match.group("bare") or ""
            fields[field_match.group(1)] = value
            continue
        slot = _SLOT.match(line)
        if slot and len(slot.group(1)) == 2:
            flush()
            current = slot.group(2).strip().strip("'\"")
    flush()
    return slots, []


def _section(lines: list[str], name: str) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^{name}:\s*(?:#.*)?$", line):
            start = index + 1
            break
    if start is None:
        return []
    body: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith((" ", "\t", "-", "#")):
            break
        body.append(line)
    return body


def _root_scalar(lines: list[str], key: str) -> str:
    for line in lines:
        if not line or line[0].isspace() or line.startswith(("#", "-")):
            continue
        match = _ROOT.match(line)
        if match and match.group("key") == key:
            quoted = match.group("quoted")
            if quoted is not None:
                return quoted.strip()
            return (match.group("bare") or "").strip()
    return ""


def _first_region(lines: list[str]) -> str:
    for line in _section(lines, "accounts"):
        match = re.match(
            r"^\s+region:\s*(?:(?P<q>['\"])(?P<quoted>.*)(?P=q)|(?P<bare>\S+))\s*(?:#.*)?$",
            line,
        )
        if not match:
            continue
        quoted = match.group("quoted")
        if quoted is not None:
            return quoted.strip()
        return (match.group("bare") or "").strip()
    return ""


def _split_field(text: str) -> tuple[str, str]:
    key, value = text.split(":", 1)
    return key.strip(), _unquote(value.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        if value[0] == "'":
            inner = inner.replace("''", "'")
        return inner
    return value
