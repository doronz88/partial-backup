import plistlib
import sqlite3
from hashlib import sha1
from pathlib import Path

import pytest

from partial_backup.backup import MANIFEST_DB_VERSION, Backup, ReferenceBackup, mbfile_archive

PREF = "Library/Preferences/com.example.test.plist"


def mbfile(blob: bytes) -> dict:
    archive = plistlib.loads(blob)
    objects = archive["$objects"]
    root = objects[archive["$top"]["root"].data]
    resolved = {k: (objects[v.data] if isinstance(v, plistlib.UID) else v) for k, v in root.items()}
    return resolved


def rows(backup_dir: Path) -> dict:
    conn = sqlite3.connect(backup_dir / "Manifest.db")
    try:
        return {(d, p): (fid, flags, mbfile(blob))
                for fid, d, p, flags, blob in conn.execute("SELECT fileID, domain, relativePath, flags, file FROM Files")}
    finally:
        conn.close()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "unback"
    (root / "HomeDomain" / "Library" / "Preferences").mkdir(parents=True)
    (root / "HomeDomain" / "Library" / "Preferences" / "com.example.test.plist").write_bytes(b"payload")
    (root / "HomeDomain" / "user_0_group_20_mode_600_class_4").mkdir()
    (root / "HomeDomain" / "user_0_group_20_mode_600_class_4" / "secret").write_bytes(b"x")
    (root / "HomeDomain" / ".DS_Store").write_bytes(b"junk")
    return root


def test_writes_modern_layout(source: Path, tmp_path: Path) -> None:
    output = Backup.create_backup_from_directory(source).write_to_directory(tmp_path / "out", "ident")
    assert output == tmp_path / "out" / "ident"
    for name in ("Info.plist", "Manifest.plist", "Status.plist", "Manifest.db"):
        assert (output / name).exists()

    conn = sqlite3.connect(output / "Manifest.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == MANIFEST_DB_VERSION
    conn.close()

    manifest = plistlib.loads((output / "Manifest.plist").read_bytes())
    assert manifest["Version"] == "10.0" and manifest["IsEncrypted"] is False and manifest["BackupKeyBag"]
    status = plistlib.loads((output / "Status.plist").read_bytes())
    assert status["Version"] == "3.3" and status["IsFullBackup"] is False


def test_manifest_rows(source: Path, tmp_path: Path) -> None:
    output = Backup.create_backup_from_directory(source).write_to_directory(tmp_path / "out")
    entries = rows(output)
    assert set(entries) == {("HomeDomain", p) for p in ("", "Library", "Library/Preferences", PREF, "secret")}

    # Every parent directory, including the domain root, is listed so the device can create it
    root_fid, root_flags, root = entries[("HomeDomain", "")]
    assert root_flags == 2
    assert (root["Mode"], root["UserID"], root["GroupID"]) == (0o40711, 501, 501)
    assert entries[("HomeDomain", "Library")][2]["Mode"] == 0o40755

    fid, flags, pref = entries[("HomeDomain", PREF)]
    assert fid == sha1(f"HomeDomain-{PREF}".encode()).hexdigest()
    assert flags == 1
    assert (pref["Mode"], pref["UserID"], pref["GroupID"], pref["ProtectionClass"]) == (0o100644, 501, 501, 3)
    assert pref["Size"] == 7 and pref["Digest"] == sha1(b"payload").digest() and pref["RelativePath"] == PREF
    assert (output / fid[:2] / fid).read_bytes() == b"payload"

    secret = entries[("HomeDomain", "secret")][2]
    assert (secret["Mode"], secret["UserID"], secret["GroupID"], secret["ProtectionClass"]) == (0o100600, 0, 20, 4)

    inodes = [e[2]["InodeNumber"] for e in entries.values()]
    assert len(set(inodes)) == len(inodes)


def test_reference_backup(source: Path, tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    reference.mkdir()
    conn = sqlite3.connect(reference / "Manifest.db")
    conn.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    conn.execute("INSERT INTO Files VALUES ('a', 'HomeDomain', 'Library/Preferences', 2, ?)",
                 (mbfile_archive("Library/Preferences", 0o40700, 501, 501, 9, 0, 4),))
    conn.execute("INSERT INTO Files VALUES ('b', 'HomeDomain', 'secret', 1, ?)",
                 (mbfile_archive("secret", 0o100644, 501, 501, 10, 1, 1),))
    conn.commit()
    conn.close()
    (reference / "Manifest.plist").write_bytes(plistlib.dumps({
        "BackupKeyBag": b"keybag", "Lockdown": {"UniqueDeviceID": "udid"}, "IsEncrypted": False,
        "Applications": {"com.example": {}}}))
    (reference / "Info.plist").write_bytes(plistlib.dumps({
        "Unique Identifier": "udid", "Applications": {"com.example": {}}, "Installed Applications": ["com.example"]}))
    (reference / "Status.plist").write_bytes(plistlib.dumps({}))

    backup = Backup.create_backup_from_directory(source, ReferenceBackup.load(reference))
    output = backup.write_to_directory(tmp_path / "out")
    entries = rows(output)

    preferences = entries[("HomeDomain", "Library/Preferences")][2]
    assert (preferences["Mode"], preferences["ProtectionClass"]) == (0o40700, 4)
    # Explicit metadata hints win over the reference
    secret = entries[("HomeDomain", "secret")][2]
    assert (secret["Mode"], secret["UserID"], secret["GroupID"], secret["ProtectionClass"]) == (0o100600, 0, 20, 4)

    manifest = plistlib.loads((output / "Manifest.plist").read_bytes())
    assert manifest["BackupKeyBag"] == b"keybag" and manifest["Lockdown"] == {"UniqueDeviceID": "udid"}
    assert manifest["Applications"] == {}
    info = plistlib.loads((output / "Info.plist").read_bytes())
    assert info["Unique Identifier"] == "udid" and info["Applications"] == {}
    assert "Installed Applications" not in info


def test_legacy_layout(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "legacy"
    Backup.create_backup_from_directory(source).write_legacy_to_directory(output)
    for name in ("Info.plist", "Manifest.plist", "Status.plist", "Manifest.mbdb"):
        assert (output / name).exists()
    assert (output / sha1(f"HomeDomain-{PREF}".encode()).hexdigest()).read_bytes() == b"payload"


def test_app_domains_are_listed_in_applications(tmp_path: Path) -> None:
    root = tmp_path / "unback"
    for domain in ("AppDomain-com.example.app", "AppDomainGroup-group.com.example", "AppDomainPlugin-com.example.ext"):
        (root / domain / "Documents").mkdir(parents=True)
        (root / domain / "Documents" / "file").write_bytes(b"x")
    output = Backup.create_backup_from_directory(root).write_to_directory(tmp_path / "out")
    applications = plistlib.loads((output / "Manifest.plist").read_bytes())["Applications"]
    assert applications == {
        "com.example.app": {"CFBundleIdentifier": "com.example.app", "ContainerContentClass": "Data/Application"},
        "group.com.example": {"CFBundleIdentifier": "group.com.example", "ContainerContentClass": "Shared/AppGroup"},
        "com.example.ext": {"CFBundleIdentifier": "com.example.ext", "ContainerContentClass": "Data/PluginKitPlugin"},
    }
    assert rows(output)[("AppDomain-com.example.app", "Documents/file")][2]["UserID"] == 501
