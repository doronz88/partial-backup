# 🗂️ partial-backup: Metadata-Aware Partial Backup Creator

This utility scans a given directory in a structured *"unbacked"* format and generates a `Backup` object that can be
written back as a valid backup. It preserves directory and file metadata such as ownership (`user_`), group (`group_`),
and file mode (`mode_`), and skips common junk files.

---

## 📦 Features

- Recursively scans a directory organized by *domain* (e.g., `HomeDomain`)
- Supports embedded metadata in directory names (`user_501_group_0_mode_755`)
- Preserves and serializes:
  - File contents
  - Directory structure
  - Ownership and permissions
- Skips system-specific noise like `.DS_Store` and `Thumbs.db`
- Outputs a fully reconstructable `Backup` object
- Simple CLI using [Typer](https://typer.tiangolo.com/)

---

## 🛠️ Installation

```bash
pip install partial-backup
```

## 🧪 Example Usage

Assume your source directory is structured like this:

```none
unback/HomeDomain/
├── user_501_group_0_mode_777/Library
│   └── Preferences/
│       └── com.example.settings.plist
```

To generate the backup:

```shell
partial-backup unback/ output/
```

It will:

- Detect `HomeDomain`
- Extract user/group/mode from directories like `user_501_group_0_mode_777`
- Generate a Backup object
- Save the reconstructed backup to `output/`

## ♻️ Restore the Backup

The generated backup is compatible with [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), and can be
restored to an iOS device using:

```shell
pymobiledevice3 backup2 restore /path/to/backup --source . --no-copy --system
```

## 📁 Metadata Syntax

This tool supports optional metadata hints in folder names:

| Syntax                       | Meaning ---                |
|------------------------------|----------------------------|
| `user_501`                   | File owned by user `501`   |
| `group_20`                   | File belongs to group `20` |
| `mode_755`                   | File or directory mode     |
| `user_501_group_20_mode_644` | All of the above           |

These metadata markers are automatically removed from paths and applied to the appropriate file or directory entry.

## ⛔ Ignored Files

The following files and folders are skipped automatically:

- `.DS_Store`
- `Thumbs.db`
- `desktop.ini`
- `.Spotlight-V100`
- `.Trashes`

## API Overview

```python
from pathlib import Path
from partial_backup.backup import Backup

backup = Backup.create_backup_from_directory(Path('/path/to/unback'))
backup.write_to_directory(Path('/path/to/output'))
```

## 🙏 Acknowledgments

Huge thanks to [@JJTech0130](https://github.com/JJTech0130) for his insights and foundational work on the backup DB
implementation.
