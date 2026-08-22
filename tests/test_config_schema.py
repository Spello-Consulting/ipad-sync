"""Tests for the configuration schema."""

import pytest
from sc_foundation import SCConfigManager

from config_schemas import ConfigSchema

VALID_CONFIG = """
General:
  AppName: ipad-sync
  SimulationMode: False
AppleTV:
  Playlist: "iPad Sync"
  MediaFolder: "/Volumes/Data/Video"
iPad:
  AppName: "Infuse"
  MinimumFreeSpaceGB: 1
"""

MISSING_REQUIRED = """
General:
  AppName: ipad-sync
iPad:
  AppName: "Infuse"
"""


def _load(tmp_path, text):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(text)
    return SCConfigManager(
        config_file=str(config_file), validation_schema=ConfigSchema().validation
    )


def test_valid_config_loads(tmp_path):
    """A well-formed config loads and exposes its values."""
    config = _load(tmp_path, VALID_CONFIG)
    assert config.get("AppleTV", "Playlist") == "iPad Sync"
    assert config.get("iPad", "AppName") == "Infuse"


def test_optional_fields_absent(tmp_path):
    """Optional fields default to None when absent."""
    config = _load(tmp_path, VALID_CONFIG)
    assert config.get("iPad", "BundleID", default=None) is None


def test_missing_required_section_raises(tmp_path):
    """Omitting the required AppleTV section is rejected."""
    with pytest.raises(RuntimeError):
        _load(tmp_path, MISSING_REQUIRED)
