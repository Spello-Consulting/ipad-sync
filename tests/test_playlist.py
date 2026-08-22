"""Tests for the Apple TV playlist service."""

import subprocess  # noqa: S404 - only used to build fakes and assert calls
from pathlib import Path

import pytest

from ipad_sync.appletv import (
    PlaylistError,
    PlaylistService,
    hfs_to_posix,
    posix_to_hfs,
)


@pytest.mark.parametrize(
    ("hfs", "posix"),
    [
        (
            "Data_IT:Multimedia:Video:Movie.m4v",
            "/Volumes/Data_IT/Multimedia/Video/Movie.m4v",
        ),
        ("Data_Mobile:file.m4v", "/Volumes/Data_Mobile/file.m4v"),
        ("Data_IT:Multimedia:", "/Volumes/Data_IT/Multimedia"),
    ],
)
def test_hfs_to_posix(hfs, posix):
    """HFS colon paths convert to /Volumes POSIX paths."""
    assert hfs_to_posix(hfs) == posix


def test_hfs_to_posix_empty_raises():
    """An empty HFS path is rejected."""
    with pytest.raises(ValueError, match="empty"):
        hfs_to_posix(":")


def _service(tmp_path):
    script_dir = tmp_path / "applescript"
    script_dir.mkdir()
    (script_dir / "playlist_exists.applescript").write_text("-- stub\n")
    return PlaylistService("iPad Sync", tmp_path / "media", script_dir)


def test_exists_true(tmp_path, monkeypatch):
    """A '1' from the script means the playlist exists."""
    service = _service(tmp_path)

    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "/usr/bin/osascript"
        assert cmd[-1] == "iPad Sync"
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert service.exists() is True


def test_exists_false(tmp_path, monkeypatch):
    """A '0' from the script means the playlist does not exist."""
    service = _service(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_k: subprocess.CompletedProcess(cmd, 0, stdout="0", stderr=""),
    )
    assert service.exists() is False


def test_missing_script_raises(tmp_path):
    """A missing AppleScript file raises PlaylistError."""
    service = PlaylistService("iPad Sync", tmp_path / "media", tmp_path / "empty")
    with pytest.raises(PlaylistError, match="not found"):
        service.exists()


def test_osascript_failure_raises(tmp_path, monkeypatch):
    """A non-zero osascript exit raises PlaylistError."""
    service = _service(tmp_path)

    def fake_run(cmd, **_kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PlaylistError, match="boom"):
        service.exists()


# -- read() parsing --------------------------------------------------------------

_GS = "\x1d"  # group separator (matches read_playlist.applescript)
_RS = "\x1e"  # record separator

_MEDIA = "/Volumes/Data_IT/Multimedia/Video"


def _read_service(tmp_path):
    """A service rooted at the standard media folder for read() tests.

    Returns:
        A :class:`PlaylistService` rooted at the standard media folder.
    """
    return PlaylistService("iPad Sync", Path(_MEDIA), tmp_path / "applescript")


def _blob(names, locations, shows=None):
    """Assemble a names/locations/shows blob as the AppleScript would emit it.

    Returns:
        The combined blob string with the expected separators.
    """
    result = _RS.join(names) + _GS + _RS.join(locations)
    if shows is not None:
        result += _GS + _RS.join(shows)
    return result


def test_read_maps_paths_and_flags_missing(tmp_path, monkeypatch):
    """read() converts HFS paths, computes relative paths and flags missing files."""
    service = _read_service(tmp_path)
    blob = _blob(
        ["Movie A", "Amok Time"],
        [
            "Data_IT:Multimedia:Video:Movie A.m4v",
            "Data_IT:Multimedia:Video:Star Trek:Season 2:Amok Time.m4v",
        ],
    )
    monkeypatch.setattr(service, "_run_script", lambda *_a: blob)

    present = "/Volumes/Data_IT/Multimedia/Video/Movie A.m4v"
    stats = {present: (True, 500)}
    monkeypatch.setattr(service, "_stat_path", lambda p: stats.get(p, (False, 0)))

    items = service.read()

    assert len(items) == 2
    assert items[0].rel_path == "Movie A.m4v"
    assert items[0].size == 500
    assert items[0].missing is False
    assert items[0].abs_path == present
    assert items[0].name == "Movie A"

    assert items[1].rel_path == "Star Trek/Season 2/Amok Time.m4v"
    assert items[1].missing is True
    assert items[1].size == 0


def test_read_empty_output_returns_empty(tmp_path, monkeypatch):
    """A missing/empty playlist yields no items."""
    service = _read_service(tmp_path)
    monkeypatch.setattr(service, "_run_script", lambda *_a: "")
    assert service.read() == []


def test_read_path_outside_media_folder_falls_back_to_abs(tmp_path, monkeypatch):
    """A track outside the media folder keeps its absolute path as rel_path."""
    service = _read_service(tmp_path)
    blob = _blob(["Stray"], ["Other_Vol:Movies:Stray.m4v"])
    monkeypatch.setattr(service, "_run_script", lambda *_a: blob)
    monkeypatch.setattr(service, "_stat_path", lambda _p: (True, 10))

    items = service.read()

    assert items[0].rel_path == "/Volumes/Other_Vol/Movies/Stray.m4v"
    assert items[0].missing is False


# -- posix_to_hfs + write operations ---------------------------------------------


@pytest.mark.parametrize(
    ("posix", "hfs"),
    [
        (
            "/Volumes/Data_IT/Multimedia/Video/Movie.m4v",
            "Data_IT:Multimedia:Video:Movie.m4v",
        ),
        ("/Volumes/Data_Mobile/file.m4v", "Data_Mobile:file.m4v"),
    ],
)
def test_posix_to_hfs_roundtrip(posix, hfs):
    """POSIX /Volumes paths convert back to HFS and round-trip with hfs_to_posix."""
    assert posix_to_hfs(posix) == hfs
    assert hfs_to_posix(hfs) == posix


def test_posix_to_hfs_outside_volumes_raises():
    """A path outside /Volumes cannot be converted."""
    with pytest.raises(ValueError, match="outside /Volumes"):
        posix_to_hfs("/Users/nick/file.m4v")


def test_add_tracks_writes_paths_and_returns_count(tmp_path, monkeypatch):
    """add_tracks passes the POSIX paths in a temp file and parses the count."""
    service = _read_service(tmp_path)
    captured = {}

    def fake_run(name, playlist_name, list_file):
        captured["name"] = name
        captured["playlist"] = playlist_name
        captured["content"] = Path(list_file).read_text(encoding="utf-8")
        return "2"

    monkeypatch.setattr(service, "_run_script", fake_run)
    count = service.add_tracks(["/Volumes/Data_IT/a.m4v", "/Volumes/Data_IT/b.m4v"])

    assert count == 2
    assert captured["name"] == "add_to_playlist.applescript"
    assert captured["playlist"] == "iPad Sync"
    assert captured["content"] == "/Volumes/Data_IT/a.m4v\n/Volumes/Data_IT/b.m4v"


def test_add_tracks_empty_is_noop(tmp_path, monkeypatch):
    """add_tracks with no paths does not invoke AppleScript."""
    service = _read_service(tmp_path)
    monkeypatch.setattr(
        service,
        "_run_script",
        lambda *_a: (_ for _ in ()).throw(AssertionError("called")),
    )
    assert service.add_tracks([]) == 0


def test_remove_tracks_converts_to_hfs(tmp_path, monkeypatch):
    """remove_tracks writes HFS location strings and parses the count."""
    service = _read_service(tmp_path)
    captured = {}

    def fake_run(name, _playlist_name, list_file):
        captured["name"] = name
        captured["content"] = Path(list_file).read_text(encoding="utf-8")
        return "1"

    monkeypatch.setattr(service, "_run_script", fake_run)
    count = service.remove_tracks(["/Volumes/Data_IT/Movie.m4v"])

    assert count == 1
    assert captured["name"] == "remove_from_playlist.applescript"
    assert captured["content"] == "Data_IT:Movie.m4v"


def test_read_missing_value_location_keeps_name_and_show(tmp_path, monkeypatch):
    """A deleted TV track keeps its name and show; display prepends the show."""
    service = _read_service(tmp_path)
    blob = _blob(["Pilot"], ["missing value"], ["About a Boy"])
    monkeypatch.setattr(service, "_run_script", lambda *_a: blob)

    items = service.read()

    assert len(items) == 1
    assert items[0].missing is True
    assert items[0].abs_path is None
    assert items[0].name == "Pilot"
    assert items[0].show == "About a Boy"
    assert items[0].display_name == "About a Boy - Pilot"


def test_read_prepends_show_for_tv_but_not_movies(tmp_path, monkeypatch):
    """TV tracks show 'Show - Episode'; movies (empty show) show just the name."""
    service = _read_service(tmp_path)
    blob = _blob(
        ["Amok Time", "Across the Universe"],
        [
            "Data_IT:Multimedia:Video:Star Trek:Amok Time.m4v",
            "Data_IT:Multimedia:Video:Across the Universe.m4v",
        ],
        ["Star Trek", "missing value"],
    )
    monkeypatch.setattr(service, "_run_script", lambda *_a: blob)
    monkeypatch.setattr(service, "_stat_path", lambda _p: (True, 100))

    items = service.read()

    assert items[0].show == "Star Trek"
    assert items[0].display_name == "Star Trek - Amok Time"
    assert items[1].show is None
    assert items[1].display_name == "Across the Universe"
