# Plan: Report iPad free space at startup (issue #1)

Implements [issue #1](https://github.com/NickElseySpelloC/ipad-sync/issues/1):
report the iPad's free space during the startup checks, and investigate why the
reported free space (8.8 GB) disagrees with iOS *Settings > General > iPad
Storage* (45.42 GB).

## Investigation findings (the "why the numbers differ" part)

I probed the connected iPad three ways. All device-wide sources agree with each
other and with the ~8.8 GB the app reports today:

| Source | Key | Value |
|---|---|---|
| lockdown `com.apple.disk_usage` | `AmountDataAvailable` | 8.87 GiB (9.53 GB) |
| House Arrest AFC `get_device_info()` | `FSFreeBytes` | 9.07 GiB (9.74 GB) |
| iOS *Settings* (per the issue) | "Available" | 45.42 GB |

Key points:

- The AFC figure the app uses today is **not** sandbox-limited — AFC
  `FSTotalBytes` is 238 GiB (the whole data volume), so the ~8.8 GB is the real,
  device-wide free space, not just Infuse's container.
- The ~37 GB gap is **APFS purgeable space**: evictable caches, offloaded-app
  bodies and non-pinned iCloud files that iOS reclaims on demand. iOS *Settings*
  adds purgeable space into its "Available" number; the lockdown/AFC APIs report
  only what is *immediately* writable. Apple exposes **no** lockdown/AFC key for
  the purgeable-inclusive figure, so the app cannot reproduce 45.42 GB exactly.

**Conclusion:** the current 8.8 GB is correct as "free space guaranteed writable
right now" — the safest number for the `to-ipad` space-fit guard. The right fix
is therefore to (a) report it clearly at startup, (b) explain the purgeable gap
so the number is no longer surprising, rather than chase an unreproducible value.

A latent bug worth fixing while here: `IPadStorageManager.free_space_bytes()`
falls back to the `FSFreeBlocks` key and returns it *as bytes*. Blocks are not
bytes (× `FSBlockSize`), so that fallback would report ~4096× too small. In
practice `FSFreeBytes` is always present, but the fallback is wrong.

## Proposed changes

### 1. `device.py` — expose device-wide disk usage
Add a `DiskUsage` dataclass (to `models.py`) and `IPadDevice.disk_usage()` that
reads lockdown `com.apple.disk_usage` and returns total capacity + available
bytes. This works right after `connect()` — i.e. during startup, before any
House Arrest session is opened.

```python
@dataclass(frozen=True)
class DiskUsage:
    total_capacity: int   # TotalDiskCapacity  (device nominal size)
    available: int        # AmountDataAvailable (immediately-writable free space)
```

### 2. `protocols.py` — add `disk_usage()` to `DeviceProbe`
So the startup checker can call it and the fakes conform structurally.

### 3. `startup.py` — new informational check + result field
- Add `free_space_bytes` / `total_capacity_bytes` to `StartupResult`.
- Add `_check_free_space()` (called from `run()`, non-simulate branch). It is
  **informational** — like the USB-speed check it never aborts. It logs, e.g.:

  > iPad storage: 8.9 GB free of 238.2 GB.
  > (iOS Settings may show more free space — it also counts reclaimable
  > "purgeable" storage that isn't immediately available for transfers.)

### 4. `storage/ipad.py` — single source of truth + fallback fix
Reimplement `free_space_bytes()` to delegate to `self._device.disk_usage()` so
the number used by the `to-ipad` guard is identical to the one reported at
startup. Keep `afc_device_info()` on the device (still handy), but fix the
`FSFreeBlocks` fallback there / remove the buggy key handling.

### 5. Tests
- `tests/fakes.py`: give `FakeDevice` a `disk_usage()` returning a canned
  `DiskUsage` (configurable), and add the method to `FakeAfcDevice`.
- `tests/test_startup.py`: assert the free-space line is logged with the
  purgeable note, and that it never aborts when disk usage is unavailable.
- `tests/test_storage_ipad.py`: update `test_free_space_reads_device_info` to the
  new `disk_usage()`-backed path.
- `tests/test_protocols.py`: `DeviceProbe` conformance still holds.

### 6. Docs
Update `docs/app-requirements.md` / `implementation-plan.md` free-space notes to
mention the lockdown `disk_usage` source and the purgeable caveat.

## Open question for you

The startup report will show the **immediately-writable** free space (~8.8 GB),
with a note explaining Settings counts purgeable space on top. That's the honest,
reproducible number and the correct basis for the "will this sync fit" guard.
If instead you'd prefer the report to *approximate* the Settings figure, we'd
have to make assumptions about purgeable space that Apple doesn't expose — happy
to discuss, but I'd recommend against it. Let me know before I implement.
