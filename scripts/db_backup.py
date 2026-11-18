#!/usr/bin/env python3
"""Create an atomic, consistent SQLite snapshot; never overwrite a target."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote


def snapshot(source: Path, destination: Path) -> dict:
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().absolute()
    if not source.is_file():
        raise ValueError('源数据库必须是普通文件')
    if os.path.lexists(destination):
        raise FileExistsError(f'拒绝覆盖已有目标：{destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.sqlite-snapshot-', dir=destination.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        uri = f'file:{quote(str(source), safe="/")}?mode=ro'
        with sqlite3.connect(uri, uri=True, timeout=30) as origin:
            with sqlite3.connect(temporary_path) as target:
                origin.backup(target)
                integrity = target.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity != 'ok':
                    raise ValueError(f'数据库完整性检查失败：{integrity}')
                tables = target.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        # A same-directory hard link publishes atomically and refuses an existing destination.
        os.link(temporary_path, destination)
        return {'path': str(destination), 'integrity_check': integrity, 'tables': tables, 'bytes': destination.stat().st_size}
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        import json
        print(json.dumps(snapshot(args.source, args.destination), ensure_ascii=False))
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f'{args.action} 失败：{exc}\n')


if __name__ == '__main__':
    main()
