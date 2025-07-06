#!/usr/bin/env python3
import argparse
import logging
import os
import stat
import sys
from pathlib import Path
from typing import List, Optional

import pathspec
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

# Initialize Rich console
console = Console()

# Configure logging
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console)],
)
log = logging.getLogger("pa-permission-denied-simulator")


def setup_argparse() -> argparse.ArgumentParser:
    """
    Sets up the argument parser for the tool.

    Returns:
        argparse.ArgumentParser: The configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description="Simulates permission denied errors on a target system based on a provided permission set."
    )

    parser.add_argument(
        "target_path",
        help="The target directory or file to simulate permission denied errors on.",
        type=Path,
    )
    parser.add_argument(
        "-p",
        "--permissions",
        help="The permission string to set (e.g., '0777', '0644'). Defaults to removing all permissions.",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-e",
        "--exclude",
        help="Pathspec pattern to exclude files/directories from permission changes.",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Apply permission changes recursively to subdirectories.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    return parser


def apply_permission_change(target_path: Path, permissions: Optional[str], exclude_spec: Optional[pathspec.PathSpec] = None):
    """
    Applies the specified permission change to the target path.

    Args:
        target_path (Path): The path to the file or directory to modify.
        permissions (Optional[str]): The permission string to apply (e.g., "0777"). If None, removes all permissions.
        exclude_spec (Optional[pathspec.PathSpec]): A PathSpec object containing patterns to exclude from the change.
    """
    try:
        if exclude_spec and exclude_spec.match_file(str(target_path)):
            log.debug(f"Skipping excluded path: {target_path}")
            return

        if permissions:
            try:
                mode = int(permissions, 8)  # Convert octal string to integer
                os.chmod(target_path, mode)
                log.info(f"Changed permissions of {target_path} to {permissions}")
            except ValueError:
                log.error(f"Invalid permission string: {permissions}")
                return 1
        else:
            # Remove all permissions.  This is platform-specific.  Using a simple approach for Unix.
            if os.name == 'posix':
              os.chmod(target_path, 0) # Removes all permissions
              log.info(f"Removed all permissions from {target_path}")
            else:
              log.warning(f"Removing all permissions is only supported on Unix-like systems.  Skipping {target_path}")
    except OSError as e:
        log.error(f"Failed to change permissions of {target_path}: {e}")


def process_path(target_path: Path, permissions: Optional[str], recursive: bool, exclude_spec: Optional[pathspec.PathSpec] = None):
    """
    Processes the target path and applies permission changes, recursively if specified.

    Args:
        target_path (Path): The path to the file or directory to process.
        permissions (Optional[str]): The permission string to apply (e.g., "0777"). If None, removes all permissions.
        recursive (bool): Whether to apply the changes recursively.
        exclude_spec (Optional[pathspec.PathSpec]): A PathSpec object containing patterns to exclude from the change.
    """
    if not target_path.exists():
        log.error(f"Target path does not exist: {target_path}")
        return 1

    if target_path.is_file():
        apply_permission_change(target_path, permissions, exclude_spec)
    elif target_path.is_dir():
        apply_permission_change(target_path, permissions, exclude_spec)

        if recursive:
            for root, _, files in os.walk(target_path):
                for file in files:
                    file_path = Path(root) / file
                    apply_permission_change(file_path, permissions, exclude_spec)
                for dir_name in os.listdir(root): # Iterate through the directories
                    dir_path = Path(root) / dir_name
                    if dir_path.is_dir(): # Check if the entry is a directory
                        apply_permission_change(dir_path, permissions, exclude_spec)

    return 0


def main() -> int:
    """
    The main function of the tool.

    Returns:
        int: The exit code of the tool.
    """
    parser = setup_argparse()
    args = parser.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)
        log.debug("Verbose logging enabled.")

    target_path = args.target_path.resolve()  # Resolve to absolute path
    permissions = args.permissions
    recursive = args.recursive
    exclude_pattern = args.exclude

    if exclude_pattern:
        try:
            exclude_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, exclude_pattern.splitlines()
            )
        except Exception as e:
            log.error(f"Invalid exclude pattern: {e}")
            return 1
    else:
        exclude_spec = None

    if not target_path.exists():
        console.print(
            Panel(
                Text(f"Error: Target path does not exist: {target_path}", style="bold red"),
                title="Error",
                border_style="red",
            )
        )
        return 1

    if permissions and not (len(permissions) == 3 or len(permissions) == 4) :
        console.print(
            Panel(
                Text(f"Error: Permissions must be 3 or 4 digits, e.g. 777 or 0777", style="bold red"),
                title="Error",
                border_style="red",
            )
        )
        return 1
    
    return process_path(target_path, permissions, recursive, exclude_spec)


if __name__ == "__main__":
    sys.exit(main())