# Apple TV ↔ Infuse Playlist Sync — Session Notes

## Project goal

Build a tool to keep an Infuse (iPad) media library in sync with an Apple TV app playlist called **"iPad Sync"**, across multiple Macs that each hold their own local copy of the media library. Two directions:

1. **TV playlist → Infuse**: read the "iPad Sync" playlist contents (title + file path) from the TV app, copy those media files to Infuse on the iPad (possibly via an intermediary like Dropbox for the file transfer).
2. **Infuse → TV playlist**: inspect Infuse's app storage on the iPad, and rebuild/recreate a matching playlist in the TV app from what's actually present there.

Sync direction (one-way vs bidirectional) and conflict handling are not yet decided — flagged as a design question for later, possibly needs a state/manifest file to track what's already synced (similar in spirit to existing heartbeat/verification patterns used elsewhere in Nick's stack).

---

## Part 1: Reading the TV app playlist (AppleScript)

The macOS **TV app** (successor to iTunes for movies/TV) still exposes an AppleScript dictionary similar to the old Music app. Tracks in a playlist have a `location` property with the file's alias/path — but only for **locally stored files**; streamed/rented content has no location.

### Key discovery: `POSIX path of (location of t)` can fail even when the file plays fine

- `location of t` returns an **alias** (works fine, e.g. `alias "Data_Mobile:Multimedia:Video:...m4v"`).
- `POSIX path of (location of t)` forces AppleScript to **resolve** that alias against the actual mounted volume/identity — and this can throw `Can't get POSIX path of location of file track id... ` even when the volume (`Data_Mobile`, an APFS volume) is mounted and the TV app can play the file. Root cause is believed to be an **alias identity mismatch** (AppleScript aliases store more than just a path — a volume/file identity — which can go stale even when the volume name matches).
- **Workaround that works reliably**: use `(location of t) as text` instead — this just reads the stored HFS-style path string out of the alias record without touching the filesystem, and does NOT fail. Then convert the HFS path (colon-delimited, e.g. `Data_Mobile:Multimedia:Video:A.I. Artificial Intelligence [2001].m4v`) to POSIX manually:

```applescript
on hfsPathToPosix(hfsPath)
    if hfsPath ends with ":" then set hfsPath to text 1 thru -2 of hfsPath
    set AppleScript's text item delimiters to ":"
    set pathParts to text items of hfsPath
    set AppleScript's text item delimiters to "/"
    set posixPath to "/Volumes/" & (pathParts as text)
    set AppleScript's text item delimiters to ""
    return posixPath
end hfsPathToPosix
```

(Note: `/Volumes/` prefix is correct for a non-boot data volume like `Data_Mobile`. If ever pointed at a boot volume, the correct prefix is just `/`.)

### Working "list playlist contents" script (slow version, per-track loop)

```applescript
on hfsPathToPosix(hfsPath)
    if hfsPath ends with ":" then set hfsPath to text 1 thru -2 of hfsPath
    set AppleScript's text item delimiters to ":"
    set pathParts to text items of hfsPath
    set AppleScript's text item delimiters to "/"
    set posixPath to "/Volumes/" & (pathParts as text)
    set AppleScript's text item delimiters to ""
    return posixPath
end hfsPathToPosix

tell application "TV"
    set thePlaylist to playlist "iPad Sync"
    set output to ""
    repeat with t in tracks of thePlaylist
        set theName to name of t
        try
            set hfsPath to (location of t) as text
            set thePath to my hfsPathToPosix(hfsPath)
        on error
            set thePath to "(no file — not locally stored)"
        end try
        set output to output & theName & " -- " & thePath & linefeed
    end repeat
    return output
end tell
```

**Confirmed working** against the real "iPad Sync" playlist, but AppleScript's `repeat` is slow because each property access is an IPC round-trip.

### Next planned step (not yet built): fast bulk version

Idea discussed: pull `name of every track of thePlaylist` and `location of every track of thePlaylist` in **two bulk calls** instead of per-track, join with a delimiter (e.g. linefeed), pass both blobs back to Python via `osascript`, and do the **HFS→POSIX path conversion in Python** rather than AppleScript (since Python string handling is nicer, and it means AppleScript is only used for the minimal data pull). Caveat flagged: bulk `location of every track` might fail all-or-nothing if any track in the playlist has no `location` (e.g. mixed file/streaming playlist) — may need to filter to `every file track of thePlaylist` first, or wrap in try/catch.

### Reverse direction: build a TV playlist from a list of file paths

If files are **already in the TV library**, match by `location` (compare as alias, not string) and `duplicate` into a new playlist:

```applescript
on run
    set filePaths to {"/Users/nick/Movies/clip1.mp4", "/Users/nick/Movies/clip2.mp4"}
    tell application "TV"
        set newPlaylist to make new playlist with properties {name:"My New Playlist"}
        repeat with thePath in filePaths
            set targetFile to POSIX file thePath as alias
            set matchFound to false
            repeat with t in tracks
                try
                    if (location of t) is targetFile then
                        duplicate t to newPlaylist
                        set matchFound to true
                        exit repeat
                    end if
                end try
            end repeat
            if not matchFound then log "No library match for: " & thePath
        end repeat
    end tell
end run
```

Note: looping the whole library per path is O(n·m) — fine for small counts, but flagged as needing a smarter lookup (build a path→track map once) if this gets slow at scale.

If files are **not yet** in the TV library, use `add` instead (imports + adds in one step):

```applescript
tell application "TV"
    set newPlaylist to make new playlist with properties {name:"My New Playlist"}
    add (POSIX file "/Users/nick/Movies/clip1.mp4") to newPlaylist
end tell
```

**Important complication for the multi-machine design**: since each Mac holds its own copy of the media library, **file paths won't match across machines**. Matching for the reverse-sync direction will likely need to be done on **filename** (or another stable identifier — e.g. `persistent ID` in the TV app's track properties, or embedded file metadata) rather than full path.

### AppleScript debugging notes (for reference)

- Script Editor has **no breakpoints/step-through debugging** — only `log` statements (View → Show Log / ⌘L), running selected code chunks, or `display dialog`/`display alert` as manual pause points.
- Script Debugger (Late Night Software, ~$129) is the paid option with real breakpoints/step-into if this becomes worthwhile.
- To inspect what properties/fields are available on a scripting object (e.g. a track), dump `properties of t` — returns a full record with actual values. Also useful: File → Open Dictionary → TV in Script Editor to browse the full `track`/`file track` class definitions.
- Confirmed actual `properties of t` output for a `file track` item includes: `class`, `id`, `index`, `name`, `persistent ID`, `database ID`, `date added`, `time`, `duration`, `director`, `genre`, `size`, `year`, `kind`, `media kind`, `played count`, `rating`, `description`, `long description`, `release date`, `location` (alias), and more.

---

## Part 2: Reading/writing Infuse's storage on iPad (via USB)

Finder's "Files" tab per-app (what you see when you select the iPad in Finder → Files → Infuse) is **not a real filesystem mount** — it's backed by Apple's AFC (Apple File Conduit) protocol over the USB/lockdown device pairing, same mechanism iTunes used to use.

### Tool: `pymobiledevice3`

Pure-Python (no native/Xcode deps) implementation of Apple's device protocols, including the **House Arrest** service — AFC scoped to a single app's sandbox/Documents folder (exactly what Finder's per-app Files view uses).

**Install (uv-based, matching Nick's existing tooling patterns):**
```bash
uv add pymobiledevice3
# or for a standalone script:
uv run --with pymobiledevice3 python your_script.py
# or PEP 723 inline metadata at top of script:
# /// script
# dependencies = ["pymobiledevice3"]
# ///
```

**One-time pairing (per Mac — each machine needs its own pairing with the iPad):**
```bash
pymobiledevice3 usbmux list          # confirm iPad shows up over USB
pymobiledevice3 lockdown pair        # accept Trust prompt on iPad
```

**Finding Infuse's bundle ID:**
```bash
pymobiledevice3 apps list | grep -i infuse
```
Believed to be `com.firecore.infuse` — **confirm from actual output**, not assumed.

### Actual current CLI structure (confirmed from `pymobiledevice3 apps -h` on Nick's machine — note some naming differs from what was initially assumed)

```
pymobiledevice3 apps list                                    # list installed apps
pymobiledevice3 apps query                                   # metadata for bundle ids
pymobiledevice3 apps install / uninstall
pymobiledevice3 apps afc <bundle_id> --documents              # interactive AFC shell (ls, cd, etc.)
pymobiledevice3 apps webdav <bundle_id> --documents           # serve container over WebDAV for mounting
pymobiledevice3 apps pull <bundle_id> <remote> <local> --documents
pymobiledevice3 apps push <bundle_id> <local> <remote> --documents
pymobiledevice3 apps rm <bundle_id> <remote> --documents
pymobiledevice3 apps install-record
```

There is **no dedicated `ls`/list-files CLI subcommand** — listing is done either via the interactive `afc` shell, or programmatically via the Python API (see below). `webdav` mounting was attempted but Nick had problems getting the mount to work, so the Python API route is the current plan.

### Working approach: list files programmatically without an interactive shell

```python
# /// script
# dependencies = ["pymobiledevice3"]
# ///

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService

BUNDLE_ID = "com.firecore.infuse"

lockdown = create_using_usbmux()
house_arrest = HouseArrestService(lockdown=lockdown, bundle_id=BUNDLE_ID, documents_only=True)

for entry in house_arrest.listdir("/"):
    print(entry)
```

Run with `uv run list_infuse.py`.

For richer info (size, file-vs-directory) per entry, `house_arrest.stat(full_path)` was suggested — **not yet confirmed working**; exact field names (e.g. `st_size`, `st_ifmt`) need verifying against the installed version since the API/CLI has shifted across pymobiledevice3 releases. Suggested next step: print one raw `stat()` result to see actual available keys before building the recursive walker.

```python
def walk(path="/"):
    for name in house_arrest.listdir(path):
        full_path = f"{path.rstrip('/')}/{name}"
        info = house_arrest.stat(full_path)
        yield full_path, info
```

### Known gotchas / things to double check next session

- `house_arrest.listdir("/")` — if root path notation errors out, try `"."` instead.
- `stat()` return shape not yet verified on Nick's installed pymobiledevice3 version — check this first.
- WebDAV mount (`pymobiledevice3 apps webdav ... --documents` + `mount_webdav`) was attempted and **did not work** for Nick — abandoned in favor of direct Python API (`listdir`/`push`/`pull`/`rm`) rather than treating it as a real mounted filesystem.
- Pairing (`lockdown pair`) is per-Mac — will need to be repeated on each machine (NUC/sydneyapp, Mac Minis, MacBook Air) that will run this sync tool against the iPad over USB.

---

## Open design questions / not yet decided

1. **Matching key across machines**: since local media file paths differ per Mac, matching between TV playlist entries and Infuse files (and vice versa) will need to use **filename** or another stable ID (e.g. TV app's `persistent ID`), not full path.
2. **Transfer mechanism for Step 1** (TV playlist → Infuse): whether to copy actual media files through a Dropbox intermediary (could be large) vs. just exporting a manifest and handling transfer separately.
3. **Sync direction**: one-way (TV playlist = source of truth) vs. bidirectional, and whether a state/manifest file is needed to track what's already been synced.
4. **Fast bulk AppleScript listing**: not yet built — plan is bulk `name of every track` / `location of every track` pulled once each, joined with a delimiter, parsed and path-converted in Python.
5. Where this ends up living in Nick's project structure — likely a new project using his standard `uv` + `pyproject.toml` + `sc_utility`/`DateHelper` conventions, not yet started.

---

## Environment notes

- TV app playlist name: **"iPad Sync"**
- Local media volume: **Data_Mobile** — APFS volume, 5.0 TB, confirmed mounted at `/Volumes/Data_Mobile` (not the boot volume)
- Target iPad app: **Infuse**, bundle ID believed to be `com.firecore.infuse` (needs confirming via `pymobiledevice3 apps list`)
- Connection: iPad connected via USB to a MacBook Air for current testing
