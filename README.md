# ipad-sync

This is a basic Python application template. It provides support for logging and 
yaml configuration file management.

## Using this as a template

Use the `pyutil/new_project.sh` script to clone a local copy of this template project. 
The script will do a find-and-replace the two placeholders throughout:

- `ipad-sync` → your app's name (also the systemd service name).
- `Tool to sync an Apple TV playlist to the Infuse app` → a one-line description.

## Prerequisites

- Python 3.13+ — `brew install python@3.13`
- [uv](https://docs.astral.sh/uv/) — `brew install uv`

`scripts/launch.sh` runs `uv sync` to install all dependencies into the virtual
environment automatically.

> **macOS note:** to let the app reach the local network, allow your terminal/IDE
> under *System Settings > Privacy and Security > Local Network*.

## Configuration

Config lives in [configs/development.yaml](configs/development.yaml) and
[configs/production.yaml](configs/production.yaml). Secrets are **not** stored in
YAML — they come from environment variables (see the `.env` templates below).

## Environment files

The app loads a `.env` file (via `python-dotenv`). Two templates are provided
(`.env.dev.template`, `.env.prod.template`) using 1Password `op://` references, plus
`tests/.env.test.template` for the test suite. Copy/inject the appropriate one:

```bash
ln -s .env.dev.template .env.target
```

## Running the app

You can run it immediately by: 

```bash
./scripts/launch.sh
```

This will select the relevant config file (using the APP_CONFIG environment variable), do a `uv sync` and then
launch the app.

## Usage

The app takes a command plus the usual `--config` option:

```bash
uv run python src/main.py ipad-apps --config configs/development.yaml
```

Every run first performs the startup checks (USB connection, trust/pairing,
media folder, playlist probe, and iPad app lookup) before the command runs.

Commands:

| Command | Status | Description |
|---|---|---|
| `ipad-apps` | ✅ Phase 1 | List installed iPad apps with display name and bundle id |
| `list-playlist` | ✅ Phase 2 | List the Apple TV playlist contents |
| `list-ipad` | ✅ Phase 2 | List the Infuse Documents contents |
| `compare` | ✅ Phase 2 | Compare playlist vs iPad by relative path |
| `to-ipad` | ⏳ Phase 3 | Mirror playlist media onto the iPad |
| `to-playlist` | ⏳ Phase 4 | Rebuild the playlist from the iPad |

Flags: `--simulate` runs against a local folder instead of an iPad (see
`General.SimulationMode`/`SimulationRoot` in the config); `--yes` skips
confirmation prompts.

## Development

```bash
uv sync --extra all          # install dev dependencies
uv run ruff format src tests # format
uv run ruff check src tests  # lint
uv run mypy src              # type-check (strict)
uv run pytest                # run the test suite
```

## Running via systemd

To run automatically at boot (e.g. on a Raspberry Pi):

### 1. Create a service file

```bash
sudo cp deploy/ipad-sync.service /etc/systemd/system/ipad-sync.service
sudo nano /etc/systemd/system/ipad-sync.service
```

### 2. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable ipad-sync
sudo systemctl start ipad-sync
```

### 3. View logs

```bash
journalctl -u ipad-sync -f
```