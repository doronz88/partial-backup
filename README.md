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
└── Library
    └── Preferences/
        └── com.example.settings.plist
```

To generate the backup:

```shell
partial-backup unback/ output/
```

It will:

- Detect `HomeDomain`
- Extract user/group/mode/protection class from directories like `user_501_group_0_mode_755`
- List every parent directory, including the domain root, so the device can create them
- Write an iOS 10+ backup (`Manifest.db`) into `output/partial-backup/`

### Matching the device exactly

The device applies the owner, mode and data protection class listed in the backup, including to directories that
already exist. The built-in defaults follow a real iOS 27.2 backup, but for exact values take a small backup of the
same area from the target device and pass it as a reference:

```shell
pymobiledevice3 backup2 backup bk/ --full --only sms
partial-backup unback/ output/ --reference bk/<UDID>
```

Entries present in the reference keep its attributes (explicit metadata hints still win), and the device's own
`Info.plist`/`Manifest.plist` metadata and keybag are reused.

## ♻️ Restore the Backup

The generated backup is compatible with [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), and can be
restored to an iOS device without erasing it:

```shell
pymobiledevice3 backup2 restore output/ --source partial-backup --no-copy --system --no-remove --skip-apps
```

- `--no-remove` keeps everything the backup doesn't list.
- `--system` is required unless `--reference` was used: `HomeDomain`, `MediaDomain` and the other domains in the
  device's `MobileBackup.framework/Domains.plist` are "system domains", and the device skips them unless the host asks
  for system files or the backup's `Lockdown.DeviceClass` matches the device.
- The device restores only what its `Domains.plist` allows. Paths outside a domain's rules (e.g. anything in
  `MediaDomain` other than its `RelativePathsToBackupAndRestore`, such as `Media/Recordings` or
  `Library/SMS/Attachments`) and some whole domains (e.g.
  `SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles`) are skipped silently: the restore still
  reports success.
- App containers (`AppDomain-<bundle id>`, `AppDomainGroup-<group id>`, `AppDomainPlugin-<bundle id>`) of installed
  apps are restored too; their identifiers are listed in `Manifest.plist`'s `Applications` automatically, since the
  device skips app domains that aren't listed there.
- The device reboots when done and shows the post-restore Setup Assistant screens; backups are refused
  (`MBErrorDomain/212`) until they are completed. `--no-reboot` doesn't avoid this, it only postpones it.

For iOS 9 and older, `--legacy` writes the old `Manifest.mbdb` format directly into `output/`.

## 📁 Metadata Syntax

This tool supports optional metadata hints in folder names:

| Syntax                               | Meaning                               |
|--------------------------------------|---------------------------------------|
| `user_501`                           | File owned by user `501`              |
| `group_20`                           | File belongs to group `20`            |
| `mode_755`                           | File or directory mode                |
| `class_4`                            | Data protection class                 |
| `user_501_group_20_mode_644_class_3` | All of the above                      |

These metadata markers are automatically removed from paths and applied to the entries below them. Without hints,
files are `0644`, directories `0755`, files use protection class `3`, and the owner is `mobile` (`501`) for domains
under `/var/mobile` (`HomeDomain`, `AppDomain-*`, ...) and `root` otherwise.

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
backup.write_to_directory(Path('/path/to/output'))  # -> /path/to/output/partial-backup
```

## 🙏 Acknowledgments

Huge thanks to [@JJTech0130](https://github.com/JJTech0130) for his insights and foundational work on the backup DB
implementation.
