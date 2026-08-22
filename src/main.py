"""Main module for the Tool to sync an Apple TV playlist to the Infuse app app."""

import argparse
import os
import platform
import sys
from pathlib import Path

from dotenv import load_dotenv
from sc_foundation import (
    SCCommon,
    SCConfigManager,
    SCLogger,
)

from config_schemas import ConfigSchema
from ipad_sync.appletv import PlaylistService
from ipad_sync.commands import (
    cmd_compare,
    cmd_ipad_apps,
    cmd_list_ipad,
    cmd_list_playlist,
    cmd_to_ipad,
)
from ipad_sync.device import IPadDevice
from ipad_sync.startup import StartupChecker, StartupError
from ipad_sync.storage import SimulationStorageManager, StorageManager
from ipad_sync.storage.ipad import IPadStorageManager

CONFIG_FILE = "config.yaml"

# All supported operations (command-line command names).
COMMANDS = (
    "ipad-apps",
    "list-playlist",
    "list-ipad",
    "compare",
    "to-ipad",
    "to-playlist",
)

# Commands implemented so far (others report "not yet implemented").
IMPLEMENTED_COMMANDS = frozenset({
    "ipad-apps",
    "list-playlist",
    "list-ipad",
    "compare",
    "to-ipad",
})

# Commands that need a connected Documents storage session.
STORAGE_COMMANDS = frozenset({"list-ipad", "compare", "to-ipad"})


def parse_command_line_args() -> dict[str, str | bool | None]:
    """Parse and validate command line arguments.

    Returns:
        dict: Dictionary containing parsed arguments with keys:
            - 'command': The operation to run (always present).
            - 'config_file': Path to configuration file (always present).
            - 'homedir': Project home directory (may be None).
            - 'simulate': Whether the --simulate flag was set.
            - 'assume_yes': Whether the --yes flag was set.
    """
    parser = argparse.ArgumentParser(
        description="ipad-sync - Tool to sync an Apple TV playlist to the Infuse app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py ipad-apps
  python main.py list-playlist --config /path/to/config.yaml
  python main.py to-ipad --yes
  python main.py list-ipad --simulate
        """,
    )

    parser.add_argument(
        "command",
        choices=COMMANDS,
        help="The operation to perform",
    )

    parser.add_argument(
        "--homedir",
        type=str,
        metavar="PATH",
        help="Specify the project home directory",
    )

    parser.add_argument(
        "--config",
        type=str,
        metavar="FILE",
        help=f"Path to configuration file (default: {CONFIG_FILE})",
    )

    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run against a local folder instead of a connected iPad",
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (assume yes)",
    )

    args = parser.parse_args()

    if args.homedir:
        homedir = Path(args.homedir)
        if not homedir.exists():
            print(
                f"ERROR: Specified homedir does not exist: {args.homedir}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not homedir.is_dir():
            print(
                f"ERROR: Specified homedir is not a directory: {args.homedir}",
                file=sys.stderr,
            )
            sys.exit(1)
        base_dir = homedir.resolve()
        os.environ["SC_FOUNDATION_PROJECT_ROOT"] = str(base_dir)
    else:
        base_dir = Path(SCCommon.get_project_root())

    if args.config:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = base_dir / config_path
        config_file = str(config_path.resolve())
        if not Path(config_file).exists():
            print(
                f"ERROR: Configuration file does not exist: {config_file}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not Path(config_file).is_file():
            print(
                f"ERROR: Configuration path is not a file: {config_file}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        config_file = CONFIG_FILE

    return {
        "command": args.command,
        "config_file": config_file,
        "homedir": str(base_dir) if args.homedir else None,
        "simulate": args.simulate,
        "assume_yes": args.yes,
    }


def report_fatal_heartbeat(logger: SCLogger) -> None:
    """Report a fatal error to the heartbeat monitor and log it.

    Args:
        logger: The logger instance used to report the heartbeat failure.
    """
    logger.ping_heartbeat(is_fail=True)


def initialize_config_and_logging(
    cmd_args: dict[str, str | bool | None],
) -> tuple[SCConfigManager, SCLogger]:
    """Initialize the configuration manager.

    If either fails, the program will exit with an error message.

    Args:
        cmd_args: Command line arguments containing the config file path.

    Returns:
        tuple[SCConfigManager, SCLogger]: Initialized configuration manager and logger instances.
    """
    schemas = ConfigSchema()
    assert isinstance(schemas.validation, dict)

    try:
        config_file = cmd_args["config_file"]
        assert isinstance(config_file, str)
        config = SCConfigManager(
            config_file=config_file, validation_schema=schemas.validation
        )
    except RuntimeError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        logger = SCLogger(config.get_logger_settings(), heartbeat_config=None)
    except RuntimeError as e:
        print(f"Logger initialisation error: {e}", file=sys.stderr)
        sys.exit(1)
    else:
        logger.log_message("", "summary")
        logger.log_message("", "summary")
        logger.log_message(
            "Tool to sync an Apple TV playlist to the Infuse app application starting.",
            "summary",
        )
        logger.log_message(f"Configuration file: {cmd_args['config_file']}", "debug")
        if cmd_args["homedir"]:
            logger.log_message(f"Home directory: {cmd_args['homedir']}", "debug")

        if logger.get_fatal_error():
            logger.log_message(
                "Application has recovered after a prior fatal failure.", "summary"
            )
            logger.clear_fatal_error()
            logger.send_email(
                "ipad-sync recovery",
                "ipad-sync run was successful after a prior failure.",
            )

    return config, logger


def run_command(
    config: SCConfigManager,
    logger: SCLogger,
    cmd_args: dict[str, str | bool | None],
) -> None:
    """Run startup checks and dispatch the requested command.

    Args:
        config: The loaded configuration manager.
        logger: The initialised logger.
        cmd_args: Parsed command-line arguments.
    """
    log = logger.log_message
    command = cmd_args["command"]

    simulate = bool(config.get("General", "SimulationMode", default=False)) or bool(
        cmd_args["simulate"]
    )
    project_root = Path(SCCommon.get_project_root())
    media_folder = Path(str(config.get("AppleTV", "MediaFolder")))

    playlist = PlaylistService(
        playlist_name=str(config.get("AppleTV", "Playlist")),
        media_folder=media_folder,
        script_dir=project_root / "applescript",
        log=log,
    )

    device = None if simulate else IPadDevice(log=log)
    try:
        checker = StartupChecker(
            app_name=str(config.get("iPad", "AppName")),
            media_folder=media_folder,
            configured_bundle_id=config.get("iPad", "BundleID", default=None),
            device=device,
            playlist=playlist,
            simulate=simulate,
            log=log,
        )
        try:
            startup = checker.run()
        except StartupError as exc:
            logger.log_fatal_error(f"Startup check failed: {exc}")
            return

        if command not in IMPLEMENTED_COMMANDS:
            log(
                f"Command '{command}' is not implemented yet (coming in a later build phase).",
                "summary",
            )
            return

        if command == "ipad-apps":
            cmd_ipad_apps(startup, log)
        elif command == "list-playlist":
            cmd_list_playlist(playlist, log)
        elif command in STORAGE_COMMANDS:
            storage = _build_storage(
                simulate=simulate,
                config=config,
                project_root=project_root,
                device=device,
                bundle_id=startup.bundle_id,
            )
            with storage:
                if command == "list-ipad":
                    cmd_list_ipad(storage, log)
                elif command == "compare":
                    cmd_compare(playlist, storage, log)
                elif command == "to-ipad":
                    min_free_gb = int(
                        config.get("iPad", "MinimumFreeSpaceGB", default=1) or 1
                    )
                    cmd_to_ipad(
                        playlist,
                        storage,
                        log,
                        min_free_gb=min_free_gb,
                        assume_yes=bool(cmd_args["assume_yes"]),
                    )
    finally:
        if device is not None:
            device.close()


def _build_storage(
    *,
    simulate: bool,
    config: SCConfigManager,
    project_root: Path,
    device: IPadDevice | None,
    bundle_id: str | None,
) -> StorageManager:
    """Build the storage manager appropriate to the run mode.

    Args:
        simulate: Whether to use the local simulation backend.
        config: The loaded configuration manager.
        project_root: The resolved project root directory.
        device: The connected device (required when not simulating).
        bundle_id: The target app's bundle id (required when not simulating).

    Returns:
        A (not-yet-connected) storage manager.

    Raises:
        StartupError: If a device-backed manager is requested without a device.
    """
    if simulate:
        configured = config.get("General", "SimulationRoot", default=None)
        root = Path(str(configured)) if configured else project_root / "sim-documents"
        return SimulationStorageManager(root)
    if device is None or bundle_id is None:
        msg = "Internal error: device and bundle id are required for iPad storage."
        raise StartupError(msg)
    return IPadStorageManager(device, bundle_id)


def main() -> None:
    """Main entry point."""
    load_dotenv()  # Load .env file if present (no-op if absent)
    print(f"Starting ipad-sync on {platform.system()}")

    cmd_args = parse_command_line_args()

    config, logger = initialize_config_and_logging(cmd_args)

    run_command(config, logger, cmd_args)


if __name__ == "__main__":
    main()
