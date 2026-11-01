from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print

from partial_backup.backup import DEFAULT_IDENTIFIER, Backup, ReferenceBackup


def create_backup_directory(
    source: Path,
    output: Path,
    identifier: Annotated[str, typer.Option(
        help="Name of the backup directory created under OUTPUT; pass it to `backup2 restore --source`.")
    ] = DEFAULT_IDENTIFIER,
    reference: Annotated[Optional[Path], typer.Option(
        help="A real backup's <UDID> directory taken from the target device (e.g. "
             "`pymobiledevice3 backup2 backup --only sms`). Its device metadata and the exact attributes of matching "
             "entries are reused.")
    ] = None,
    legacy: Annotated[bool, typer.Option(
        help="Write the legacy iOS <= 9 format (Manifest.mbdb) directly into OUTPUT.")
    ] = False,
) -> None:
    """
    Construct a backup directory from a given source directory given in an `unback` format
    """
    backup = Backup.create_backup_from_directory(source, ReferenceBackup.load(reference) if reference else None)
    print(f"Constructing the following backup structure into: {output}")
    print(backup.files)
    if legacy:
        backup.write_legacy_to_directory(output)
        restore_source = "."
    else:
        backup.write_to_directory(output, identifier)
        restore_source = identifier
    print("[bold][green]Done![/green][/bold]")
    print("[bold]Consider restoring this backup using:[/bold]")
    print(f"[magenta]pymobiledevice3 backup2 restore {output} --source {restore_source} --no-copy --system "
          f"--no-remove --skip-apps[/magenta]")


def cli() -> None:
    typer.run(create_backup_directory)


if __name__ == "__main__":
    cli()
