"""Configuration schemas for use with the SCConfigManager class."""


class ConfigSchema:
    """Base class for configuration schemas."""

    def __init__(self):

        self.validation = {
            "General": {
                "type": "dict",
                "required": False,
                "nullable": True,
                "schema": {
                    "AppName": {"type": "string", "required": False, "nullable": True},
                },
            },
            "AppleTV": {
                "type": "dict",
                "required": True,
                "nullable": False,
                "schema": {
                    "Playlist": {"type": "string", "required": True},
                    "MediaFolder": {"type": "string", "required": True},
                },
            },
            "iPad": {
                "type": "dict",
                "required": True,
                "nullable": False,
                "schema": {
                    "AppName": {"type": "string", "required": True},
                    "MinimumFreeSpaceGB": {"type": "integer", "required": False, "nullable": True},
                },
            },
        }
