# ipad-sync — Implementation Plan

> Status: **Draft for review**. This plan covers all four build phases from
> [app-requirements.md](app-requirements.md). Each phase ends with a hard stop for
> your review before the next begins.

## 1. Objective recap

A macOS-side Python CLI that two-way mirrors media between an Apple TV **playlist**
("iPad Sync") and the **Infuse** app's `Documents` on a USB-connected iPad:

- **`to-ipad`** — copy playlist media onto the iPad (mirror; deletes extras).
- **`to-playlist`** — rebuild the playlist from what's on the iPad.

Because several Macs each hold their own media copy at a *different* absolute path,
the sync key is always the **path relative to the media root**, never the absolute
path. Absolute paths are only ever (re)constructed by joining a machine's
`AppleTV.MediaFolder` with a stored relative path.

---

## 2. Key technical findings (verified against the installed code)

These drive the architecture and correct some assumptions in
[apple-tv-infuse-sync-notes.md](apple-tv-infuse-sync-notes.md).

### 2.1 `pymobiledevice3` 10.x is fully async ⚠️

The notes doc shows a **synchronous** usage
(`for entry in house_arrest.listdir("/")`). That is **stale** — in the installed
version (`>=10.10.0`) every device operation is a coroutine:

| Operation | Call (all `async`) |
|---|---|
| Create lockdown client | `await create_using_usbmux()` |
| List USB devices | `await list_devices()` |
| Pair / trust | `await lockdown.pair()` |
| Vend Infuse Documents | `await HouseArrestService.create(lockdown, bundle_id, documents_only=True)` |
| List dir | `await afc.listdir(path)` |
| Stat | `await afc.os_stat(path)` → `StatResult` NamedTuple |
| Free space | `await lockdown.get_value(domain="com.apple.disk_usage")` → `AmountDataAvailable` (device-wide, immediately-writable free space). Note: iOS *Settings* shows more because it also counts reclaimable APFS purgeable storage, which no lockdown/AFC key exposes. |
| Copy up / down | `await afc.push(local, remote)` / `await afc.pull(remote, local)` |
| Delete | `await afc.rm(path, force=True)` |
| Make dirs | `await afc.makedirs(path)` |
| Recursive walk | `async for ... in afc.walk(dir)` |
| List installed apps | `await InstallationProxyService(lockdown).get_apps()` |

`HouseArrestService` is an async context manager and holds a **live connection**;
many ops run per command against that one session, so we cannot use a throwaway
`asyncio.run()` per call.

**Architectural decision (recommended):** keep the public storage-manager interface
**synchronous** and hide async behind a facade. The concrete iPad manager owns a
single event loop for the lifetime of one CLI command and drives coroutines with
`loop.run_until_complete(...)`. Rationale:

- The CLI runs one operation and exits — no concurrency benefit from going async
  end-to-end.
- Keeps `main.py`, the simulation manager, and **pytest tests synchronous** (no need
  to add `pytest-asyncio` or await-plumb the whole app).
- The base class can define the sync contract cleanly; the simulation subclass is
  trivially sync (local filesystem), the real subclass wraps async internally.

*(Alternative considered: make the whole app async and run `asyncio.run(main())`.
Rejected for now — it pushes async into every test and the sim path for no runtime
gain. Flagged as an open question in §9 if you'd prefer it.)*

### 2.2 AppleScript path quirk (confirmed in notes, adopted here)

`POSIX path of (location of t)` can throw even for playable files. We use
`(location of t) as text` to read the raw HFS path (e.g.
`Data_IT:Multimedia:Video:...m4v`) and convert **HFS → POSIX in Python**
(`Data_IT:...` → `/Volumes/Data_IT/...`). AppleScript does only the minimal data
pull; all parsing/matching is Python.

- **Read playlist (fast/bulk):** two calls — `name of every file track` and
  `location of every file track` — joined by a delimiter, returned via `osascript`,
  split and zipped in Python. Filtering to `file track` (not `track`) avoids
  all-or-nothing failure on streamed entries with no `location`.
- **Write playlist:** an AppleScript that, given POSIX paths, matches library tracks
  and `duplicate`s them into (a freshly (re)built) "iPad Sync" playlist. Matching
  against the library is done by resolving `POSIX file thePath as alias`.

Scripts are shipped as `.applescript` text under `applescript-samples/` (or a new
`applescript/` dir) and invoked with `osascript`; parameters passed as argv where
practical, or the script emits a machine-readable blob we parse.

### 2.3 Matching key

`to-ipad` and `to-playlist` both reduce every item to a **relative POSIX path** under
its media root and compare those sets. iPad side is naturally relative (Infuse
Documents root); playlist side becomes relative by stripping `AppleTV.MediaFolder`.

---

## 3. Target module layout

```
src/
  main.py                 # CLI entry: startup checks, dispatch to a command handler
  config_schemas.py       # extended validation schema (see §4)
  ipad_sync/
    __init__.py
    models.py             # dataclasses: MediaItem, CompareResult, AppInfo, SpacePlan
    startup.py            # StartupChecker: the 5 pre-flight checks
    storage/
      __init__.py
      base.py             # StorageManager ABC + simulation implementation
      ipad.py             # IPadStorageManager (pymobiledevice3, async-behind-sync)
    appletv/
      __init__.py
      playlist.py         # PlaylistService: read/write via osascript, HFS↔POSIX
    compare.py            # pure comparison logic (relative-path set diff)
    commands.py           # one function per CLI command (ipad-apps, list-*, compare, to-*)
    console.py            # user-friendly rendering + progress reporting
applescript/
  read_playlist.applescript
  write_playlist.applescript
tests/
  test_*.py               # per-module unit tests (see per-phase test lists)
```

Design rules:
- **Every command function returns a data object** and separately renders console
  output, so higher-level commands (`to-ipad`) reuse lower-level data (`compare`,
  which reuses `list-playlist` + `list-ipad`). This satisfies the requirement that
  Phase 2 commands support both console output and reusable data.
- **All iPad storage goes through `StorageManager`.** The base class provides the
  simulation mode (backed by a local temp directory), so the whole app is testable
  with no iPad attached.

---

## 4. Configuration changes

Current schema validates `AppleTV.Playlist/MediaFolder` and
`iPad.AppName/MinimumFreeSpaceGB`. Planned additions:

- `iPad.BundleID` *(optional, nullable)* — allow pinning `com.firecore.infuse` to
  skip the display-name→bundle-id lookup; if absent we resolve by `AppName`.
- `General.SimulationMode` *(optional bool, default false)* — force the simulation
  storage manager even when an iPad is present, for dev/testing.
- `General.SimulationRoot` *(optional path)* — local dir the sim manager mirrors into
  (defaults to a temp dir).

`MinimumFreeSpaceGB` default remains 1 GB (already in dev config).

CLI: add a positional `command` argument (`ipad-apps`, `list-playlist`,
`list-ipad`, `compare`, `to-ipad`, `to-playlist`) plus `--yes` to skip confirmation
prompts and `--simulate` to force sim mode, alongside the existing `--config` /
`--homedir`.

---

## 5. Cross-cutting: the StorageManager contract

```python
class StorageManager(ABC):
    # lifecycle
    def connect(self) -> None: ...
    def close(self) -> None: ...
    # queries
    def list_files(self) -> list[MediaItem]:        # relative path + size
    def free_space_bytes(self) -> int: ...
    # mutations
    def push_file(self, local: Path, rel_path: str, on_progress=None) -> None: ...
    def remove_file(self, rel_path: str) -> None: ...
```

- **Base = simulation:** the ABC ships a concrete simulation backed by a local
  directory tree; `push`/`remove`/`list`/`free_space` all operate on that tree, with
  synthetic free-space accounting so the space-fit logic in `to-ipad` is exercisable.
- **`IPadStorageManager`** subclasses it, overriding each method to drive the async
  AFC session via an internally owned event loop. `connect()` creates the lockdown
  client + `HouseArrestService`; `close()` tears them down.

This is where the "manager class extending a base class with simulation mode"
requirement lands.

---

## 6. Phased delivery

### Phase 1 — Core structure  ⟶ *review gate*

**Deliver:**
1. **Startup checks** (`startup.py`, run for *every* command before dispatch):
   1. iPad present over USB (`list_devices`).
   2. Trust/pairing (`lockdown.pair`) — surfaces the iPad Trust dialog early.
   3. `AppleTV.MediaFolder` exists and is readable.
   4. Playlist existence probe (OK if missing; if present, confirm readable).
   5. Resolve iPad app **BundleID** from `AppName` via `get_apps()`, capturing
      `CFBundleDisplayName`→bundle-id for **all** apps (reused by `ipad-apps`).
   - Checks run up front so all approval dialogs happen before real work.
2. **StorageManager base + simulation** (§5).
3. **`ipad-apps` command** — list every installed app's DisplayName + BundleID.
4. Extend `config_schemas.py` + dev/prod YAML (§4); add `command` CLI arg + dispatch.

**Tests:** startup-check units with a mocked device layer (device present/absent,
pair fail, media folder missing, app found/not-found); simulation StorageManager
round-trip (push/list/remove/free-space); `ipad-apps` rendering from a fixture app
list; config-schema validation (valid + missing-required).

### Phase 2 — Compare features  ⟶ *review gate*

**Deliver:**
1. **`list-playlist`** — `PlaylistService.read()` via `osascript` bulk pull → HFS→POSIX
   in Python → per-track existence + size check against `MediaFolder` (mark missing).
   Returns `list[MediaItem]` (name, abs path, rel path, size, `missing` flag).
2. **`list-ipad`** — `StorageManager.list_files()` → relative path + size.
3. **`compare`** — pure set-diff on **relative paths**: `to_copy`, `to_delete`,
   `in_sync`, plus playlist items missing from disk. Returns a `CompareResult`.
   Each command renders friendly console output **and** returns its data object.

**Tests:** HFS→POSIX conversion (incl. trailing colon, non-boot volume); playlist
parser against captured `osascript` output fixtures (incl. a streamed/no-location
track filtered out); compare logic across match/nested-path/missing scenarios;
list-ipad against the simulation manager.

### Phase 3 — Mirror to iPad (`to-ipad`)  ⟶ *review gate*

**Deliver:**
- Abort if playlist empty.
- Run `compare`; show proposed adds/deletes + any playlist files missing from disk;
  **confirm before proceeding** (unless `--yes`).
- **Space fit:** project post-op free space from `get_device_info()` and file-size
  deltas; refuse to drop below `iPad.MinimumFreeSpaceGB`.
- **Deletes before copies.** Preserve relative paths (create intermediate dirs).
- **Real progress**: bytes-based, with projected total time.

**Tests:** space-fit accept/reject at the boundary; delete-before-copy ordering;
relative-path/dir creation; empty-playlist abort; confirmation gating; progress
accounting — all against the simulation manager (no iPad needed).

### Phase 4 — Update playlist (`to-playlist`)  ⟶ *review gate*

**Deliver:**
- Create playlist if absent.
- `compare` iPad vs playlist; for iPad files not in the playlist, verify they exist
  under `MediaFolder` (flag missing). Show proposed changes + missing; **confirm**.
- Remove playlist tracks not on iPad; add iPad files (join `MediaFolder` + rel path
  to get the absolute path for this machine); skip/where-needed remove missing.
- `PlaylistService.write()` via `osascript` (match library tracks, rebuild playlist).
- Progress as the playlist updates.

**Tests:** rel→abs reconstruction; add/remove set computation; missing-file
exclusion (and removal if previously present); write-script argument building
(mock `osascript`); create-if-absent path.

---

## 7. Testing & quality conventions

- `pytest` (not unittest); mock the device/`osascript` boundary — **tests never
  require a real iPad or the TV app** (simulation manager + fixtures).
- `mypy --strict`, `ruff format`, `ruff check` clean; Google-style docstrings;
  `pathlib` throughout; type hints on all signatures.
- Logging via the existing `SCLogger` (`log_message`, `log_fatal_error`); user
  prompts/progress via `console.py`.

## 8. Risks / things to verify during build

- `osascript` argument passing vs. large playlists (delimiter choice must not collide
  with names/paths — plan to use a control char / newline pairs).
- `push`/`pull` progress granularity from AFC (may need chunked writes via
  `fopen`/`fwrite` for smooth progress rather than one-shot `push`).
- Confirm `get_device_info()` free-space key names on device at first run.
- Confirm Infuse bundle id from real `get_apps()` output (`com.firecore.infuse`
  expected but not assumed).

## 9. Open questions for you

1. **Async facade vs. async-all-the-way** (§2.1) — I recommend the sync facade. OK?
   Nick: Agree
2. **Confirmation UX** — interactive `y/N` prompt acceptable, with `--yes` to bypass
   for scripted runs?
   Nick: Agree
3. **Where should AppleScript live** — new `applescript/` dir with `.applescript`
   text files (diffable, git-friendly), replacing the compiled `.scpt` sample? 
   Nick: Confirmed - use `applescript/` dir as proposed.
4. **`to-playlist` rebuild strategy** — the requirements now say remove unmatched
   tracks (not delete-and-recreate). Confirm incremental edit is preferred over the
   earlier "delete then rebuild" shortcut.
   Nick: Confirmed. This way we can preseve any play order in the playlist that we would loose if we delete and rebuild.
```
