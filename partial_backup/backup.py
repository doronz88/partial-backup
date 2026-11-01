import plistlib
import re
import sqlite3
import uuid
from base64 import b64decode
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from itertools import count
from pathlib import Path
from random import randbytes
from typing import Any, Optional

from . import mbdb
from .mbdb import FileMode

# RWX:RX:RX
DEFAULT = (FileMode.S_IRUSR | FileMode.S_IWUSR | FileMode.S_IXUSR | FileMode.S_IRGRP | FileMode.S_IXGRP |
           FileMode.S_IROTH | FileMode.S_IXOTH)

IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100", ".Trashes"}

DEFAULT_IDENTIFIER = "partial-backup"

# Domains whose contents live under /var/mobile and are owned by mobile (501:501) on the device. Everything else
# defaults to root (0:0). Observed on a real iOS 27.2 backup.
MOBILE_DOMAINS = ("HomeDomain", "MediaDomain", "CameraRollDomain", "TonesDomain", "KeyboardDomain", "HomeKitDomain",
                  "HealthDomain", "AppDomain-", "AppDomainGroup-", "AppDomainPlugin-")

# rw-r--r--
DEFAULT_FILE_MODE = FileMode.S_IRUSR | FileMode.S_IWUSR | FileMode.S_IRGRP | FileMode.S_IROTH

# (owner, group, mode) of each domain's root directory where it differs from (default_owner(), same, DEFAULT).
# Observed on a real iOS 27.2 backup. The device applies these to the existing directory, so they must be exact.
DOMAIN_ROOTS = {
    "HomeDomain": (501, 501, 0o711),
    "MediaDomain": (501, 501, 0o711),
    "CameraRollDomain": (501, 501, 0o711),
    "TonesDomain": (501, 501, 0o711),
    "KeyboardDomain": (501, 501, 0o711),
    "HomeKitDomain": (501, 501, 0o711),
    "InstallDomain": (33, 33, 0o755),
    "KeychainDomain": (64, 64, 0o755),
    "NetworkDomain": (24, 24, 0o755),
    "WirelessDomain": (25, 25, 0o755),
}

# NSFileProtectionCompleteUntilFirstUserAuthentication, the default iOS data protection class for files
DEFAULT_FILE_PROTECTION_CLASS = 3
DEFAULT_DIRECTORY_PROTECTION_CLASS = 0

# Manifest.db layout as written by iOS 10+ (Manifest.plist "Version" 10.0)
MANIFEST_DB_SCHEMA = (
    "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)",
    "CREATE INDEX FilesRelativePathIdx ON Files(relativePath)",
    "CREATE INDEX FilesFlagsIdx ON Files(flags)",
    "CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB)",
    "CREATE INDEX FilesDomainsRelativePathIdx ON Files(domain, relativePath)",
)
# Schema version of Manifest.db (`PRAGMA user_version`). With any lower value BackupAgent2 "migrates" the database
# and ends up restoring zero files.
MANIFEST_DB_VERSION = 3
MANIFEST_FLAG_FILE = 1
MANIFEST_FLAG_DIRECTORY = 2
MANIFEST_FLAG_SYMLINK = 4

# A keybag captured from some device. The restore refuses a manifest without one (MBErrorDomain/205), and for an
# unencrypted backup any keybag will do.
DEFAULT_BACKUP_KEYBAG = b64decode("""
    VkVSUwAAAAQAAAAFVFlQRQAAAAQAAAABVVVJRAAAABDud41d1b9NBICR1BH9JfVtSE1D
    SwAAACgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAV1JBUAAA
    AAQAAAAAU0FMVAAAABRY5Ne2bthGQ5rf4O3gikep1e6tZUlURVIAAAAEAAAnEFVVSUQA
    AAAQB7R8awiGR9aba1UuVahGPENMQVMAAAAEAAAAAVdSQVAAAAAEAAAAAktUWVAAAAAE
    AAAAAFdQS1kAAAAoN3kQAJloFg+ukEUY+v5P+dhc/Welw/oucsyS40UBh67ZHef5ZMk9
    UVVVSUQAAAAQgd0cg0hSTgaxR3PVUbcEkUNMQVMAAAAEAAAAAldSQVAAAAAEAAAAAktU
    WVAAAAAEAAAAAFdQS1kAAAAoMiQTXx0SJlyrGJzdKZQ+SfL124w+2Tf/3d1R2i9yNj9z
    ZCHNJhnorVVVSUQAAAAQf7JFQiBOS12JDD7qwKNTSkNMQVMAAAAEAAAAA1dSQVAAAAAE
    AAAAAktUWVAAAAAEAAAAAFdQS1kAAAAoSEelorROJA46ZUdwDHhMKiRguQyqHukotrxh
    jIfqiZ5ESBXX9txi51VVSUQAAAAQfF0G/837QLq01xH9+66vx0NMQVMAAAAEAAAABFdS
    QVAAAAAEAAAAAktUWVAAAAAEAAAAAFdQS1kAAAAol0BvFhd5bu4Hr75XqzNf4g0fMqZA
    ie6OxI+x/pgm6Y95XW17N+ZIDVVVSUQAAAAQimkT2dp1QeadMu1KhJKNTUNMQVMAAAAE
    AAAABVdSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAo2N2DZarQ6GPoWRgTiy/t
    djKArOqTaH0tPSG9KLbIjGTOcLodhx23xFVVSUQAAAAQQV37JVZHQFiKpoNiGmT6+ENM
    QVMAAAAEAAAABldSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAofe2QSvDC2cV7
    Etk4fSBbgqDx5ne/z1VHwmJ6NdVrTyWi80Sy869DM1VVSUQAAAAQFzkdH+VgSOmTj3yE
    cfWmMUNMQVMAAAAEAAAAB1dSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAo7kLY
    PQ/DnHBERGpaz37eyntIX/XzovsS0mpHW3SoHvrb9RBgOB+WblVVSUQAAAAQEBpgKOz9
    Tni8F9kmSXd0sENMQVMAAAAEAAAACFdSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kA
    AAAo5mxVoyNFgPMzphYhm1VG8Fhsin/xX+r6mCd9gByF5SxeolAIT/ICF1VVSUQAAAAQ
    rfKB2uPSQtWh82yx6w4BoUNMQVMAAAAEAAAACVdSQVAAAAAEAAAAA0tUWVAAAAAEAAAA
    AFdQS1kAAAAo5iayZBwcRa1c1MMx7vh6lOYux3oDI/bdxFCW1WHCQR/Ub1MOv+QaYFVV
    SUQAAAAQiLXvK3qvQza/mea5inss/0NMQVMAAAAEAAAACldSQVAAAAAEAAAAA0tUWVAA
    AAAEAAAAAFdQS1kAAAAoD2wHX7KriEe1E31z7SQ7/+AVymcpARMYnQgegtZD0Mq2U55u
    xwNr2FVVSUQAAAAQ/Q9feZxLS++qSe/a4emRRENMQVMAAAAEAAAAC1dSQVAAAAAEAAAA
    A0tUWVAAAAAEAAAAAFdQS1kAAAAocYda2jyYzzSKggRPw/qgh6QPESlkZedgDUKpTr4Z
    Z8FDgd7YoALY1g==""")


@dataclass
class Metadata:
    owner: Optional[int] = None
    group: Optional[int] = None
    mode: Optional[int] = None
    protection_class: Optional[int] = None


META_PATTERN = re.compile(
    r"(user_(?P<user>\d+))?"
    r"_?"
    r"(group_(?P<group>\d+))?"
    r"_?"
    r"(mode_(?P<mode>[0-7]{3,4}))?"
    r"_?"
    r"(class_(?P<protection_class>[0-9]))?"
)


def default_owner(domain: str) -> int:
    return 501 if any(domain == d or domain.startswith(d) for d in MOBILE_DOMAINS) else 0


def file_id(domain: str, path: str) -> str:
    return sha1(f"{domain}-{path}".encode()).hexdigest()


def mbfile_archive(path: str, mode: int, owner: int, group: int, inode: int, size: int, protection_class: int,
                   digest: Optional[bytes] = None, target: Optional[str] = None) -> bytes:
    """ Serialize an `MBFile` the way iOS stores it in the `file` column of `Manifest.db` (NSKeyedArchiver). """
    now = int(datetime.now().timestamp())
    root: dict[str, Any] = {
        "Birth": now,
        "Flags": 0,
        "GroupID": group,
        "InodeNumber": inode,
        "LastModified": now,
        "LastStatusChange": now,
        "Mode": mode,
        "ProtectionClass": protection_class,
        "Size": size,
        "UserID": owner,
    }
    objects: list[Any] = ["$null", root]
    root["RelativePath"] = plistlib.UID(len(objects))
    objects.append(path)
    if digest is not None:
        root["Digest"] = plistlib.UID(len(objects))
        objects.append(digest)
    if target is not None:
        root["Target"] = plistlib.UID(len(objects))
        objects.append(target)
    root["$class"] = plistlib.UID(len(objects))
    objects.append({"$classes": ["MBFile", "NSObject"], "$classname": "MBFile"})
    return plistlib.dumps({
        "$archiver": "NSKeyedArchiver",
        "$objects": objects,
        "$top": {"root": plistlib.UID(1)},
        "$version": 100000,
    }, fmt=plistlib.FMT_BINARY)


@dataclass
class BackupFile:
    path: str
    domain: str
    owner: int = 0
    group: int = 0
    mode: int = DEFAULT
    protection_class: int = DEFAULT_FILE_PROTECTION_CLASS
    inode: Optional[int] = None

    @property
    def file_id(self) -> str:
        return file_id(self.domain, self.path)

    def to_record(self) -> mbdb.MbdbRecord:
        raise NotImplementedError()

    def to_manifest_row(self, inode: int) -> tuple[str, str, str, int, bytes]:
        raise NotImplementedError()


@dataclass
class ConcreteFile(BackupFile):
    contents: bytes = b""

    def to_record(self) -> mbdb.MbdbRecord:
        if self.inode is None:
            self.inode = int.from_bytes(randbytes(8), "big")
        return mbdb.MbdbRecord(
            domain=self.domain,
            filename=self.path,
            link="",
            hash=sha1(self.contents).digest(),
            key=b"",
            mode=FileMode(self.mode | FileMode.S_IFREG),
            inode=self.inode,
            user_id=self.owner,
            group_id=self.group,
            mtime=int(datetime.now().timestamp()),
            atime=int(datetime.now().timestamp()),
            ctime=int(datetime.now().timestamp()),
            size=len(self.contents),
            flags=4,
            properties=[]
        )

    def to_manifest_row(self, inode: int) -> tuple[str, str, str, int, bytes]:
        blob = mbfile_archive(self.path, self.mode | FileMode.S_IFREG, self.owner, self.group, inode,
                              len(self.contents), self.protection_class, digest=sha1(self.contents).digest())
        return self.file_id, self.domain, self.path, MANIFEST_FLAG_FILE, blob

    def __repr__(self) -> str:
        return (f"ConcreteFile(path='{self.path}', domain='{self.domain}', "
                f"contents=b'<... length: {len(self.contents)}>', owner={self.owner}, "
                f"group={self.group}, mode={oct(self.mode)}, protection_class={self.protection_class})")


@dataclass
class Directory(BackupFile):
    protection_class: int = DEFAULT_DIRECTORY_PROTECTION_CLASS

    def to_record(self) -> mbdb.MbdbRecord:
        return mbdb.MbdbRecord(
            domain=self.domain,
            filename=self.path,
            link="",
            hash=b"",
            key=b"",
            mode=FileMode(self.mode | FileMode.S_IFDIR),
            inode=0,  # inode is not respected for directories
            user_id=self.owner,
            group_id=self.group,
            mtime=int(datetime.now().timestamp()),
            atime=int(datetime.now().timestamp()),
            ctime=int(datetime.now().timestamp()),
            size=0,
            flags=4,
            properties=[]
        )

    def to_manifest_row(self, inode: int) -> tuple[str, str, str, int, bytes]:
        blob = mbfile_archive(self.path, self.mode | FileMode.S_IFDIR, self.owner, self.group, inode, 0,
                              self.protection_class)
        return self.file_id, self.domain, self.path, MANIFEST_FLAG_DIRECTORY, blob


@dataclass
class SymbolicLink(BackupFile):
    target: str = ""

    def to_record(self) -> mbdb.MbdbRecord:
        if self.inode is None:
            self.inode = int.from_bytes(randbytes(8), "big")
        return mbdb.MbdbRecord(
            domain=self.domain,
            filename=self.path,
            link=self.target,
            hash=b"",
            key=b"",
            mode=FileMode(self.mode | FileMode.S_IFLNK),
            inode=self.inode,
            user_id=self.owner,
            group_id=self.group,
            mtime=int(datetime.now().timestamp()),
            atime=int(datetime.now().timestamp()),
            ctime=int(datetime.now().timestamp()),
            size=0,
            flags=4,
            properties=[]
        )

    def to_manifest_row(self, inode: int) -> tuple[str, str, str, int, bytes]:
        blob = mbfile_archive(self.path, self.mode | FileMode.S_IFLNK, self.owner, self.group, inode, 0,
                              self.protection_class, target=self.target)
        return self.file_id, self.domain, self.path, MANIFEST_FLAG_SYMLINK, blob


def extract_metadata_and_clean(parts: list[str]) -> tuple[list[str], Metadata]:
    cleaned_parts = []
    meta = Metadata()

    for part in parts:
        if part in IGNORED_NAMES:
            continue  # skip ignored segments entirely

        match = META_PATTERN.fullmatch(part)
        if match and any(match.group(k) for k in ("user", "group", "mode", "protection_class")):
            if match.group("user"):
                meta.owner = int(match.group("user"))
            if match.group("group"):
                meta.group = int(match.group("group"))
            if match.group("mode"):
                meta.mode = int(match.group("mode"), 8)
            if match.group("protection_class"):
                meta.protection_class = int(match.group("protection_class"))
            continue  # skip from cleaned path
        cleaned_parts.append(part)

    return cleaned_parts, meta


@dataclass
class ReferenceBackup:
    """
    A real backup taken from the target device (e.g. `pymobiledevice3 backup2 backup --only sms`). Its device
    metadata (Info.plist, Manifest.plist incl. the device's keybag) and the exact attributes of every file and
    directory it lists are reused, so restored entries keep the ownership/mode/protection class the device expects.
    """
    directory: Path
    rows: dict[tuple[str, str], dict] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> "ReferenceBackup":
        for name in ("Info.plist", "Manifest.plist", "Status.plist", "Manifest.db"):
            if not (directory / name).exists():
                raise FileNotFoundError(f"{directory / name} is missing; pass the backup's <UDID> directory")
        reference = cls(directory)
        conn = sqlite3.connect(f"file:{directory / 'Manifest.db'}?mode=ro", uri=True)
        try:
            for domain, path, blob in conn.execute("SELECT domain, relativePath, file FROM Files"):
                archive = plistlib.loads(blob)
                reference.rows[(domain, path)] = archive["$objects"][archive["$top"]["root"].data]
        finally:
            conn.close()
        return reference

    def apply(self, entry: BackupFile, explicit: Metadata) -> None:
        """ Take attributes the user didn't set explicitly from the reference backup's matching entry. """
        mbfile = self.rows.get((entry.domain, entry.path))
        if mbfile is None:
            return
        if explicit.owner is None:
            entry.owner = mbfile["UserID"]
        if explicit.group is None:
            entry.group = mbfile["GroupID"]
        if explicit.mode is None:
            entry.mode = mbfile["Mode"] & 0o7777
        if explicit.protection_class is None:
            entry.protection_class = mbfile["ProtectionClass"]

    def plist(self, name: str) -> dict:
        with open(self.directory / name, "rb") as f:
            return plistlib.load(f)


@dataclass
class Backup:
    files: list[BackupFile]
    reference: Optional[ReferenceBackup] = None

    @classmethod
    def create_backup_from_directory(cls, root: Path, reference: Optional[ReferenceBackup] = None) -> 'Backup':
        files: list[BackupFile] = []
        seen: set[tuple[str, Path]] = set()
        root = root.resolve()

        def make_entry(kind: type, domain: str, rel: Path, meta: Metadata, **kwargs) -> BackupFile:
            default_mode = DEFAULT_FILE_MODE if kind is ConcreteFile else DEFAULT
            default_group = None
            if rel == Path() and domain in DOMAIN_ROOTS:
                owner, default_group, default_mode = DOMAIN_ROOTS[domain]
            else:
                owner = default_owner(domain)
            if meta.owner is not None:
                owner = meta.owner
            group = meta.group if meta.group is not None else (default_group if default_group is not None else owner)
            entry = kind("" if rel == Path() else rel.as_posix(), domain, owner=owner, group=group,
                         mode=meta.mode if meta.mode is not None else default_mode, **kwargs)
            if meta.protection_class is not None:
                entry.protection_class = meta.protection_class
            if reference is not None:
                reference.apply(entry, meta)
            return entry

        for domain_dir in sorted(root.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name in IGNORED_NAMES:
                continue
            domain = domain_dir.name

            # The device creates directories only from the manifest's directory rows, starting at the domain root
            files.append(make_entry(Directory, domain, Path(), Metadata()))
            seen.add((domain, Path()))

            for path in sorted(domain_dir.rglob("*")):
                if path.name in IGNORED_NAMES:
                    continue

                rel_path = path.relative_to(domain_dir)
                cleaned_parts, meta = extract_metadata_and_clean(list(rel_path.parts))
                cleaned_rel_path = Path(*cleaned_parts)

                if cleaned_rel_path == Path():
                    continue  # path was only metadata or ignored

                # Ensure parent directories are created first
                for i in range(1, len(cleaned_parts)):
                    parent = Path(*cleaned_parts[:i])
                    if (domain, parent) not in seen:
                        files.append(make_entry(Directory, domain, parent, Metadata()))
                        seen.add((domain, parent))

                if path.is_symlink():
                    files.append(make_entry(SymbolicLink, domain, cleaned_rel_path, meta,
                                            target=str(path.readlink())))
                elif path.is_dir():
                    if (domain, cleaned_rel_path) not in seen:
                        files.append(make_entry(Directory, domain, cleaned_rel_path, meta))
                        seen.add((domain, cleaned_rel_path))
                elif path.is_file():
                    files.append(make_entry(ConcreteFile, domain, cleaned_rel_path, meta,
                                            contents=path.read_bytes()))

        return cls(files, reference)

    def write_to_directory(self, directory: Path, identifier: str = DEFAULT_IDENTIFIER) -> Path:
        """
        Write the backup in the iOS 10+ format (`Manifest.db`) into `directory / identifier`, which is where
        `pymobiledevice3 backup2 restore directory --source identifier` looks for it. Returns the written directory.
        """
        output = directory / identifier
        output.mkdir(parents=True, exist_ok=True)
        manifest_db = output / "Manifest.db"
        if manifest_db.exists():
            manifest_db.unlink()

        inodes = count(1)
        conn = sqlite3.connect(manifest_db)
        try:
            for statement in MANIFEST_DB_SCHEMA:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {MANIFEST_DB_VERSION}")
            for file in self.files:
                conn.execute("INSERT OR REPLACE INTO Files VALUES (?, ?, ?, ?, ?)",
                             file.to_manifest_row(next(inodes)))
                if isinstance(file, ConcreteFile):
                    blob_path = output / file.file_id[:2] / file.file_id
                    blob_path.parent.mkdir(exist_ok=True)
                    blob_path.write_bytes(file.contents)
            conn.commit()
        finally:
            conn.close()

        (output / "Status.plist").write_bytes(self.generate_status())
        (output / "Manifest.plist").write_bytes(self.generate_manifest())
        (output / "Info.plist").write_bytes(self.generate_info())
        return output

    def generate_status(self) -> bytes:  # Status.plist
        return plistlib.dumps({
            "BackupState": "new",
            "Date": datetime.now(timezone.utc).replace(tzinfo=None),
            "IsFullBackup": False,
            "SnapshotState": "finished",
            "UUID": str(uuid.uuid4()).upper(),
            "Version": "3.3",
        }, fmt=plistlib.FMT_BINARY)

    def generate_manifest(self) -> bytes:  # Manifest.plist
        manifest: dict = {
            "Applications": {},
            "BackupKeyBag": DEFAULT_BACKUP_KEYBAG,
            "Date": datetime.now(timezone.utc).replace(tzinfo=None),
            "IsEncrypted": False,
            "Lockdown": {},
            "SystemDomainsVersion": "24.0",
            "Version": "10.0",
            "WasPasscodeSet": False,
        }
        if self.reference is not None:
            reference = self.reference.plist("Manifest.plist")
            if reference.get("IsEncrypted"):
                raise ValueError("encrypted reference backups are not supported")
            for key in ("BackupKeyBag", "Lockdown", "SystemDomainsVersion", "WasPasscodeSet"):
                if key in reference:
                    manifest[key] = reference[key]
        return plistlib.dumps(manifest, fmt=plistlib.FMT_BINARY)

    def generate_info(self) -> bytes:  # Info.plist
        info: dict = {}
        if self.reference is not None:
            info = self.reference.plist("Info.plist")
            # A partial backup must never trigger app re-installation
            info["Applications"] = {}
            info.pop("Installed Applications", None)
        return plistlib.dumps(info, fmt=plistlib.FMT_BINARY)

    # Legacy (iOS <= 9) format

    def write_legacy_to_directory(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for file in self.files:
            if isinstance(file, ConcreteFile):
                with open(directory / sha1((file.domain + "-" + file.path).encode()).digest().hex(), "wb") as f:
                    f.write(file.contents)

        with open(directory / "Manifest.mbdb", "wb") as f:
            f.write(self.generate_manifest_db().to_bytes())

        with open(directory / "Status.plist", "wb") as f:
            f.write(plistlib.dumps({
                "BackupState": "new",
                "Date": datetime.fromisoformat("1970-01-01T00:00:00+00:00"),
                "IsFullBackup": False,
                "SnapshotState": "finished",
                "UUID": "00000000-0000-0000-0000-000000000000",
                "Version": "2.4"
            }))

        with open(directory / "Manifest.plist", "wb") as f:
            f.write(plistlib.dumps({
                "BackupKeyBag": DEFAULT_BACKUP_KEYBAG,
                "Lockdown": {},
                "SystemDomainsVersion": "20.0",
                "Version": "9.1"
            }))

        with open(directory / "Info.plist", "wb") as f:
            f.write(plistlib.dumps({}))

    def generate_manifest_db(self) -> mbdb.Mbdb:  # Manifest.mbdb
        # The legacy format never listed the domain root itself
        return mbdb.Mbdb(records=[file.to_record() for file in self.files if file.path != ""])
