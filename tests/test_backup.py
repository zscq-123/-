"""Tests for consistent WAL snapshots and non-destructive restore."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('db_backup', Path(__file__).parents[1] / 'scripts/db_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def test_wal_snapshot_restore_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, copied, restored = [base / n for n in ['live.db', 'copy.db', 'restored.db']]
            # Keep writer open to ensure committed rows in the WAL are included.
            writer = sqlite3.connect(source)
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE events (value TEXT)')
            writer.execute('INSERT INTO events VALUES (?)', ('模拟审计',))
            writer.commit()
            result = backup.snapshot(source, copied)
            self.assertEqual(result['integrity_check'], 'ok')
            backup.snapshot(copied, restored)
            with sqlite3.connect(restored) as db:
                self.assertEqual(db.execute('SELECT value FROM events').fetchall(), [('模拟审计',)])
            with self.assertRaises(FileExistsError):
                backup.snapshot(copied, source)
            writer.close()

    def test_invalid_database_leaves_no_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'bad.db', Path(directory) / 'copy.db'
            source.write_text('not a database')
            with self.assertRaises(sqlite3.DatabaseError):
                backup.snapshot(source, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).glob('.sqlite-snapshot-*')), [])

    def test_dangling_symlink_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'live.db', Path(directory) / 'copy.db'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE sample (id INTEGER)')
            destination.symlink_to(Path(directory) / 'absent')
            with self.assertRaises(FileExistsError):
                backup.snapshot(source, destination)
            self.assertTrue(destination.is_symlink())


if __name__ == '__main__':
    unittest.main()
