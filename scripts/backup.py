"""Согласованная копия SQLite через backup API, в том числе при работающем UI."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwriting of an existing backup.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                result = dst.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError(f"SQLite integrity_check: {result}")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main() -> None:
    from config import DB_PATH, DATA_DIR

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = args.destination or DATA_DIR / "backups" / f"macro-{stamp}.db"
    backup(DB_PATH, target)
    print(f"Backup: {target}")


if __name__ == "__main__":
    main()
