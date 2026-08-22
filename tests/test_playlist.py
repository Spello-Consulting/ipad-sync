"""Tests for the Apple TV playlist service."""

import subprocess  # noqa: S404 - only used to build fakes and assert calls

import pytest

from ipad_sync.appletv import PlaylistError, PlaylistService, hfs_to_posix


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
