# pa-permission-denied-simulator
This tool temporarily changes permissions on a target the operator names, in order to elicit real permission denied errors, reports those errors, and then restores the exact original permissions. That is the default run, and it is a true simulation: the original modes are recorded first, the change is applied, a stated probe operation is attempted per target (open for read, and open for write as well when the applied mode grants no write bit to anyone), the resulting error class and message are printed as the simulation report, and the original modes are restored in a finally block, under recursion as well. When the tool runs as root, the probe runs in a forked child that drops to the nobody account first, because root can open a mode 000 file and no denial would be seen.

Leaving changes in place is not the default and takes a two part opt in: --keep-changes together with --confirm-target carrying the exact resolved target path. A mismatch, or a missing confirmation, refuses at exit 1 before anything changes. In keep mode the original modes are written to a record file whose path is printed; the record file path is set with --record-file and defaults to permission_modes_record.json in the working directory. The --restore mode reads a record file and returns the recorded modes. Any apply or restore failure ends the run at a non zero exit, and the final line counts changed and failed paths. Helps developers test error handling and understand user experience with restricted permissions. - Focused on Tools for analyzing and assessing file system permissions

## Install
`git clone https://github.com/ShadowGuardAI/pa-permission-denied-simulator`

## Usage
`python main.py /path/to/target`
`python main.py /path/to/target -r --keep-changes --confirm-target /path/to/target`
`python main.py --restore permission_modes_record.json`

## Parameters
- `target_path`: The target directory or file to simulate permission denied errors on. Not needed with --restore.
- `-h`: Show help message and exit
- `-p`, `--permissions`: The permission string to set (e.g., '0777', '0644'). Defaults to removing all permissions.
- `-e`, `--exclude`: Pathspec pattern to exclude files/directories from permission changes.
- `-r`, `--recursive`: Apply permission changes recursively to subdirectories.
- `-v`, `--verbose`: Enable verbose logging.
- `--keep-changes`: Leave the permission changes in place instead of restoring the original permissions. Requires --confirm-target carrying the exact target path.
- `--confirm-target`: Confirmation for --keep-changes: must carry the exact resolved target path, or nothing changes and the run exits 1.
- `--record-file`: Path of the record file the original permissions are written to when changes are kept. Defaults to permission_modes_record.json in the working directory.
- `--restore`: Restore the permissions recorded in the named record file and exit. No target argument is needed in this mode.

## License
Copyright (c) ShadowGuardAI
