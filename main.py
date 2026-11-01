#!/usr/bin/env python3
import argparse
import json
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

DEFAULT_RECORD_FILE = "permission_modes_record.json"


def setup_argparse() -> argparse.ArgumentParser:
    """
    Sets up the argument parser for the tool.

    Returns:
        argparse.ArgumentParser: The configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description="Temporarily changes permissions on a target to elicit and report permission denied errors, then restores the exact original permissions. Changes are left in place only with --keep-changes together with --confirm-target."
    )

    parser.add_argument(
        "target_path",
        nargs="?",
        help="The target directory or file to simulate permission denied errors on. Not needed with --restore.",
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
    parser.add_argument(
        "--keep-changes",
        action="store_true",
        help="Leave the permission changes in place instead of restoring the original permissions. Requires --confirm-target carrying the exact target path.",
    )
    parser.add_argument(
        "--confirm-target",
        type=str,
        default=None,
        help="Confirmation for --keep-changes: must carry the exact resolved target path, or nothing changes and the run exits 1.",
    )
    parser.add_argument(
        "--record-file",
        type=str,
        default=DEFAULT_RECORD_FILE,
        help="Path of the record file the original permissions are written to when changes are kept. Defaults to permission_modes_record.json in the working directory.",
    )
    parser.add_argument(
        "--restore",
        type=str,
        default=None,
        help="Restore the permissions recorded in the named record file and exit. No target argument is needed in this mode.",
    )

    return parser


def collect_targets(target_path: Path, recursive: bool, exclude_spec: Optional[pathspec.PathSpec] = None) -> List[Path]:
    """Collects the target and, under recursion, everything under it."""
    targets: List[Path] = []

    def wanted(path: Path) -> bool:
        return not (exclude_spec and exclude_spec.match_file(str(path)))

    if target_path.is_file():
        if wanted(target_path):
            targets.append(target_path)
        return targets

    if wanted(target_path):
        targets.append(target_path)
    if recursive:
        for root, dirs, files in os.walk(target_path):
            for name in sorted(dirs):
                path = Path(root) / name
                if wanted(path):
                    targets.append(path)
            for name in sorted(files):
                path = Path(root) / name
                if wanted(path):
                    targets.append(path)
    return targets


def record_modes(targets: List[Path]) -> dict:
    """Records the exact current mode of every target."""
    modes = {}
    for path in targets:
        modes[str(path)] = stat.S_IMODE(os.stat(path).st_mode)
    return modes


def apply_mode(path: Path, mode: int) -> bool:
    """Applies one mode. Returns True on success, False on failure."""
    try:
        os.chmod(path, mode)
        log.info(f"Changed permissions of {path} to {oct(mode)}")
        return True
    except OSError as e:
        log.error(f"Failed to change permissions of {path}: {e}")
        return False


def _attempt(path: Path, write: bool) -> str:
    """One probe attempt in this process. Returns a result line."""
    try:
        if path.is_dir():
            if write:
                return "skipped for directories"
            os.listdir(path)
        else:
            fd = os.open(path, os.O_RDWR if write else os.O_RDONLY)
            os.close(fd)
        return "succeeded (no error)"
    except OSError as e:
        return f"{type(e).__name__}: {e}"


def probe_target(path: Path, write: bool) -> List[str]:
    """
    Attempts the stated probe operations on one target and returns the
    result lines. When the tool runs as root, the probe runs in a
    forked child that first drops to the nobody account, because root
    can open a mode 000 file and no denial would be seen. Otherwise
    the probe runs as the calling user.
    """
    ops = [False]
    if write and not path.is_dir():
        ops.append(True)
    labels = {False: "read", True: "write"}

    if os.name == "posix" and hasattr(os, "fork") and os.geteuid() == 0:
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(read_fd)
                os.setgid(65534)
                os.setuid(65534)
                lines = []
                for op in ops:
                    lines.append(f"{labels[op]}={_attempt(path, op)}")
                os.write(write_fd, ("\n".join(lines)).encode())
            finally:
                os._exit(0)
        os.close(write_fd)
        data = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            data += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        results = {}
        for part in data.decode().split("\n"):
            if "=" in part:
                key, value = part.split("=", 1)
                results[key] = value
        return [f"Probe {labels[op]} on {path}: {results.get(labels[op], 'no result')}" for op in ops]

    return [f"Probe {labels[op]} on {path}: {_attempt(path, op)}" for op in ops]


def restore_from_record(record_file: str) -> int:
    """Restore mode: reads a record file and returns the recorded modes."""
    try:
        with open(record_file, "r") as f:
            record = json.load(f)
        modes = record["modes"]
    except (OSError, ValueError, KeyError) as e:
        log.error(f"Could not read record file {record_file}: {e}")
        print(f"Restore failed: could not read record file {record_file}: {e}")
        return 1

    changed = 0
    failed = 0
    # Shallow paths first, so a directory is restored before the paths
    # under it are reached.
    for path_str in sorted(modes, key=lambda p: (len(Path(p).parts), p)):
        path = Path(path_str)
        if not path.exists():
            log.error(f"Recorded path no longer exists: {path}")
            failed += 1
            continue
        if apply_mode(path, int(modes[path_str])):
            changed += 1
        else:
            failed += 1
    print(f"Restore complete. Changed: {changed}, Failed: {failed}")
    return 1 if failed else 0


def main() -> int:
    parser = setup_argparse()
    args = parser.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)
        log.debug("Verbose logging enabled.")

    if args.restore:
        return restore_from_record(args.restore)

    if args.target_path is None:
        console.print(Panel(Text("Error: A target path is required unless --restore is used.", style="bold red"), title="Error", border_style="red"))
        return 1

    target_path = args.target_path.resolve()

    if not target_path.exists():
        console.print(Panel(Text(f"Error: Target path does not exist: {target_path}", style="bold red"), title="Error", border_style="red"))
        return 1

    permissions = args.permissions
    mode = 0
    if permissions is not None:
        if not (len(permissions) == 3 or len(permissions) == 4):
            console.print(Panel(Text("Error: Permissions must be 3 or 4 digits, e.g. 777 or 0777", style="bold red"), title="Error", border_style="red"))
            return 1
        try:
            mode = int(permissions, 8)
        except ValueError:
            console.print(Panel(Text(f"Error: Invalid permission string: {permissions}", style="bold red"), title="Error", border_style="red"))
            return 1

    if args.keep_changes:
        if args.confirm_target is None:
            console.print(Panel(Text("Error: --keep-changes requires --confirm-target carrying the exact target path. Nothing was changed.", style="bold red"), title="Error", border_style="red"))
            return 1
        if args.confirm_target != str(target_path):
            console.print(Panel(Text(f"Error: --confirm-target does not match the exact target path {target_path}. Nothing was changed.", style="bold red"), title="Error", border_style="red"))
            return 1
    elif args.confirm_target is not None:
        console.print(Panel(Text("Error: --confirm-target is only valid together with --keep-changes. Nothing was changed.", style="bold red"), title="Error", border_style="red"))
        return 1

    if args.exclude:
        try:
            exclude_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, args.exclude.splitlines()
            )
        except Exception as e:
            log.error(f"Invalid exclude pattern: {e}")
            return 1
    else:
        exclude_spec = None

    targets = collect_targets(target_path, args.recursive, exclude_spec)
    if not targets:
        log.error("No targets matched. Nothing was changed.")
        print("No targets matched. Nothing was changed.")
        return 1

    original_modes = record_modes(targets)

    if args.keep_changes:
        record = {"target": str(target_path), "permissions": permissions, "modes": original_modes}
        try:
            with open(args.record_file, "w") as f:
                json.dump(record, f, indent=2)
        except OSError as e:
            log.error(f"Could not write the record file {args.record_file}: {e}")
            print(f"Error: Could not write the record file {args.record_file}. Nothing was changed.")
            return 1
        print(f"Original permissions recorded in: {os.path.abspath(args.record_file)}")

    changed = 0
    failed = 0
    restored = 0
    try:
        # Deepest paths first, so a directory is changed only after the
        # paths under it have been reached.
        for path in sorted(targets, key=lambda p: (-len(p.parts), str(p))):
            if apply_mode(path, mode):
                changed += 1
            else:
                failed += 1

        want_write = mode & 0o222 == 0
        print("Simulation report:")
        for path in targets:
            for line in probe_target(path, want_write):
                print(line)
    finally:
        if not args.keep_changes:
            # Shallow paths first, so a directory is restored before
            # the paths under it are reached.
            for path in sorted(targets, key=lambda p: (len(p.parts), str(p))):
                try:
                    os.chmod(path, original_modes[str(path)])
                    restored += 1
                except OSError as e:
                    log.error(f"Failed to restore permissions of {path}: {e}")
                    failed += 1

    if args.keep_changes:
        print(f"Changes kept in place. Original permissions recorded in: {os.path.abspath(args.record_file)}")
        print(f"Summary: Changed: {changed}, Failed: {failed}, Restored: 0")
    else:
        print(f"Summary: Changed: {changed}, Failed: {failed}, Restored: {restored}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
