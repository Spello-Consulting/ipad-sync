"""Tests for the compare logic."""

from ipad_sync.compare import compare
from ipad_sync.models import MediaItem


def _pl(rel, size=100, missing=False):
    """Build a playlist media item.

    Returns:
        A playlist-side :class:`MediaItem`.
    """
    return MediaItem(
        rel_path=rel, size=size, name=rel, abs_path=f"/media/{rel}", missing=missing
    )


def _ip(rel, size=100):
    """Build an iPad media item.

    Returns:
        An iPad-side :class:`MediaItem`.
    """
    return MediaItem(rel_path=rel, size=size)


def test_to_copy_when_only_in_playlist():
    """A playlist file absent from the iPad is scheduled for copy."""
    result = compare([_pl("a.m4v")], [])
    assert [i.rel_path for i in result.to_copy] == ["a.m4v"]
    assert result.to_delete == []
    assert result.in_sync == []
    assert result.has_changes is True


def test_to_delete_when_only_on_ipad():
    """An iPad file absent from the playlist is scheduled for deletion."""
    result = compare([], [_ip("b.m4v")])
    assert [i.rel_path for i in result.to_delete] == ["b.m4v"]
    assert result.to_copy == []


def test_in_sync_when_relative_paths_match():
    """Matching relative paths count as in sync, not copy/delete."""
    rel = "Star Trek/Season 2/Amok Time.m4v"
    result = compare([_pl(rel)], [_ip(rel)])
    assert [i.rel_path for i in result.in_sync] == [rel]
    assert result.to_copy == []
    assert result.to_delete == []
    assert result.has_changes is False


def test_nested_path_distinguishes_from_basename():
    """Files matched by relative path, not basename alone."""
    result = compare([_pl("Show/S1/ep.m4v")], [_ip("ep.m4v")])
    assert [i.rel_path for i in result.to_copy] == ["Show/S1/ep.m4v"]
    assert [i.rel_path for i in result.to_delete] == ["ep.m4v"]


def test_missing_source_not_copied_but_retained_on_ipad():
    """A playlist file missing from disk is not copied, and its iPad copy stays."""
    rel = "gone.m4v"
    result = compare([_pl(rel, missing=True)], [_ip(rel)])
    assert result.to_copy == []
    assert result.to_delete == []  # present in playlist, so not deleted
    assert [i.rel_path for i in result.missing_source] == [rel]


def test_missing_source_absent_from_ipad_is_only_flagged():
    """A missing playlist file with no iPad copy is only flagged, not copied."""
    result = compare([_pl("gone.m4v", missing=True)], [])
    assert result.to_copy == []
    assert [i.rel_path for i in result.missing_source] == ["gone.m4v"]
