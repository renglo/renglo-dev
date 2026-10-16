# renglo-dev XXX

Installer and launcher for a local Renglo workspace. It reads `renglo.yaml` from a BOM and clones the product repos into the usual folders. The same command checks the workspace on later runs, installs anything that is missing, and starts the API and the console.

The workspace is the directory that contains this repo. Product clones stay beside it, not inside it .

```text
my-app/
  renglo-dev/          this repo, its venv, and machine-local answers
  console/
  dev/renglo-api/
  dev/renglo-lib/
  dev/<tenant>-wl/
  extensions/<handle>/
  ops/<tenant>-bom/
```

## First run

```bash
mkdir my-app
cd my-app
git clone https://github.com/renglo/renglo-dev.git
./renglo-dev/renglo --here
```

`--here` keeps the API and the console in the terminal where you ran the command, including a Cursor terminal. Drop `--here` if you want a separate macOS Terminal window for each process. The same commands are written out under [Everyday](#everyday).

The command asks for three things and remembers them in `renglo-dev/.renglo-dev.yaml` (not committed):

1. The BOM. A GitHub `owner/repo` (or URL), or a path to a checkout that already contains `renglo.yaml`. A GitHub repo is cloned to `ops/<repo>` on `develop`.
2. The AWS profile on this machine. If `aws configure list-profiles` returns one profile, that profile is used. The region comes from that profile, or from `accounts` in the BOM when the profile has none.
3. Optional emulators (`wss`, `webhook`, `ebe`). `none` is the default. Each one you turn on is cloned, installed, and opened in its own terminal.

You can answer ahead of time with `RENGLO_BOM`, `AWS_PROFILE`, `AWS_DEFAULT_REGION`, and `RENGLO_EMULATORS` (`none`, `all`, or `wss,ebe`).

`python3.12`, `git`, `node`, `npm`, `aws`, and either `gh auth login` or an SSH key are required. Missing tools are listed together.

## What gets cloned

Every entry under `packages` in `renglo.yaml`:

| Package | Folder |
| --- | --- |
| `renglo-lib`, `renglo-api` | `dev/<name>` |
| console | `console/` |
| a `*-wl` pack | `dev/<name>-wl` |
| everything else | `extensions/<repo name>` |

New clones use `develop`. A checkout that is already there is left on its current branch.

Registries, `renglo-ops`, git-convoy, launcher, and publisher are not cloned. This version does not install from a package registry. `--from-registry` explains that and stops.

## Everyday

Every command below is run from the workspace (the folder that contains `renglo-dev/`). Each one checks the workspace first and installs anything that is missing: a clone, the venv, a `pip install -e` for a new extension, or `npm install` in `console/` when `node_modules` or the lockfile is out of date. A port that is already open is left alone.

### One terminal, API and console together

```bash
./renglo-dev/renglo --here
```

Use this from a terminal you already have open, including a Cursor terminal. The API (http://127.0.0.1:5001) and the console (http://127.0.0.1:5174) both run in that terminal, and their logs are mixed in one scrollback. Emulators you turned on run there too. Ctrl+C stops all of them. This is also what happens automatically on a machine that is not macOS.

### Separate Terminal windows

```bash
./renglo-dev/renglo
```

Same check and install, then one macOS Terminal window for the API and another for the console. Each emulator you turned on gets its own window. Close a window, or press Ctrl+C in it, to stop that process. The other windows keep running.

### Install only, do not start

```bash
./renglo-dev/renglo install
```

Clones what is missing, installs Python and npm packages, and writes config stubs if those files are absent. It does not start the API or the console. Use it when you want the workspace ready and you will start it later.

### See what is missing

```bash
./renglo-dev/renglo doctor
```

Prints prerequisites, which repos are cloned and which branch each one is on, whether the venv and `node_modules` are present, which config keys are still placeholders, and which emulators are on. It does not clone, install, or start anything.

### Reinstall dependencies

```bash
./renglo-dev/renglo --refresh
```

Runs the install again even when packages are already present, then starts the stack in Terminal windows. Combine it with `--here` to reinstall and then stay in the current terminal:

```bash
./renglo-dev/renglo --here --refresh
```

`--refresh` also works with `install` if you want the reinstall without starting:

```bash
./renglo-dev/renglo install --refresh
```

Pip inside `renglo-dev/venv` uses PyPI only, so a CodeArtifact `pip.conf` on the machine does not apply while that venv is active.

## Config files

The first run writes stubs when these files are missing, and prints the paths every time. A file that already exists is not changed, including `SECRET_KEY` and `CSRF_SESSION_KEY`.

| File | Role |
| --- | --- |
| `dev/renglo-api/env_config.py` | API config. Cognito, DynamoDB, and S3 values are placeholders until you paste the operator bundle. |
| `console/.env.development` | Console config. `VITE_API_URL` points at the local API. |
| `renglo-dev/.env.launcher` | `AWS_PROFILE`, `AWS_DEFAULT_REGION`, and `RENGLO_CONFIG_PATH`. The launcher reads this file. Edit the profile here if you want a different one. |

The API is started with those exports. You do not copy `run.sh` out of `renglo-api`.

Login still needs the real Cognito and table values from your operator. The command lists every key that is still a placeholder.

## Emulators

The catalog is `emulators.yaml` in this repo (WebSocket, webhook edge, EventBridge). It is not part of the tenant BOM. To change the set later, edit the `emulators` map in `.renglo-dev.yaml`, or delete that map and run `./renglo` again to be asked.

## If a run stops halfway

Run the same command again. Clones that finished are kept, a half-written directory that is not a git checkout is reported and left for you to remove, and installs continue from what is already there.
