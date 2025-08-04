from pathlib import Path

import typer
from rich import print

from partial_backup.backup import Backup


def create_backup_directory(source: Path, output: Path) -> None:
    """
    Construct a backup directory from a given source directory given in an `unback` format
    """
    output.mkdir(parents=True, exist_ok=True)
    backup = Backup.create_backup_from_directory(source)
    print(f"Constructing the following backup structure into: {output}")
    print(backup)
    backup.write_to_directory(output)
    print("[bold][green]Done![/green][/bold]")
    print("[bold]Consider restoring this backup using:[/bold]")
    print(f"[magenta]pymobiledevice3 backup2 restore {output} --source . --no-copy --system[/magenta]")


def cli() -> None:
    typer.run(create_backup_directory)


if __name__ == "__main__":
    cli()
