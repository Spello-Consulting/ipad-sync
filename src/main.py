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

CONFIG_FILE = "config.yaml"


def parse_command_line_args() -> dict[str, str | None]:
    """Parse and validate command line arguments.

    Returns:
        dict: Dictionary containing parsed arguments with keys:
            - 'config_file': Path to configuration file (always present)
            - 'homedir': Project home directory (may be None)
    """
    parser = argparse.ArgumentParser(
        description="ipad-sync - Tool to sync an Apple TV playlist to the Infuse app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --config /path/to/config.yaml
  python main.py --homedir /opt/ipad-sync --config config.yaml
        """
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

    args = parser.parse_args()

    if args.homedir:
        homedir = Path(args.homedir)
        if not homedir.exists():
            print(f"ERROR: Specified homedir does not exist: {args.homedir}", file=sys.stderr)
            sys.exit(1)
        if not homedir.is_dir():
            print(f"ERROR: Specified homedir is not a directory: {args.homedir}", file=sys.stderr)
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
            print(f"ERROR: Configuration file does not exist: {config_file}", file=sys.stderr)
            sys.exit(1)
        if not Path(config_file).is_file():
            print(f"ERROR: Configuration path is not a file: {config_file}", file=sys.stderr)
            sys.exit(1)
    else:
        config_file = CONFIG_FILE

    return {
        "config_file": config_file,
        "homedir": str(base_dir) if args.homedir else None,
    }


def report_fatal_heartbeat(logger) -> None:
    """Report a fatal error to the heartbeat monitor and log it.

    Args:
        logger: The logger instance used to report the heartbeat failure.
    """
    logger.ping_heartbeat(is_fail=True)


def initialize_config_and_logging(cmd_args) -> tuple[SCConfigManager, SCLogger]:
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
            config_file=config_file,
            validation_schema=schemas.validation
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
        logger.log_message("Tool to sync an Apple TV playlist to the Infuse app application starting.", "summary")
        logger.log_message(f"Configuration file: {cmd_args['config_file']}", "debug")
        if cmd_args["homedir"]:
            logger.log_message(f"Home directory: {cmd_args['homedir']}", "debug")

        if logger.get_fatal_error():
            logger.log_message("Application has recovered after a prior fatal failure.", "summary")
            logger.clear_fatal_error()
            logger.send_email("ipad-sync recovery", "ipad-sync run was successful after a prior failure.")

    return config, logger


def main():
    """Main entry point."""
    load_dotenv()  # Load .env file if present (no-op if absent)
    print(f"Starting ipad-sync on {platform.system()}")

    cmd_args = parse_command_line_args()

    config, logger = initialize_config_and_logging(cmd_args)

    # Start main code here


if __name__ == "__main__":
    main()
