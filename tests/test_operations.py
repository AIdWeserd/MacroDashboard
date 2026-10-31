"""Offline checks for persistent storage and updater process lifecycle."""

import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.backup import backup
from scripts.update_data import positive_seconds, run_once


class BackupTests(unittest.TestCase):
    def test_backup_copies_committed_rows_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "macro.db"
            target = Path(directory) / "backups" / "copy.db"
            con = sqlite3.connect(source)
            try:
                con.execute("CREATE TABLE observations (value REAL)")
                con.execute("INSERT INTO observations VALUES (1.25)")
                con.commit()
                backup(source, target)
                with sqlite3.connect(target) as copied:
                    self.assertEqual(copied.execute("SELECT value FROM observations").fetchone(), (1.25,))
                # sqlite connection context managers do not close connections.
                copied.close()
                with self.assertRaises(FileExistsError):
                    backup(source, target)
            finally:
                con.close()

    def test_missing_source_does_not_create_empty_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.db"
            target = Path(directory) / "backup.db"
            with self.assertRaises(FileNotFoundError):
                backup(source, target)
            self.assertFalse(source.exists())
            self.assertFalse(target.exists())


class UpdaterTests(unittest.TestCase):
    def test_interval_must_be_positive(self):
        for invalid in ("0", "-1", "invalid"):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {"INTERVAL": invalid}):
                with self.assertRaises(ValueError):
                    positive_seconds("INTERVAL", 60)

    @patch("scripts.update_data.os.killpg", create=True)
    @patch("scripts.update_data.subprocess.Popen")
    def test_timeout_terminates_process_group(self, popen, killpg):
        process = MagicMock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired("scheduler", 1), 0]
        popen.return_value = process
        self.assertEqual(run_once(1), 124)
        self.assertEqual(killpg.call_args.args[0], 12345)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @patch("scripts.update_data.os.killpg", create=True)
    @patch("scripts.update_data.subprocess.Popen")
    def test_shutdown_also_terminates_process_group(self, popen, killpg):
        process = MagicMock(pid=12345)
        process.wait.side_effect = [SystemExit(0), 0]
        popen.return_value = process
        with self.assertRaises(SystemExit):
            run_once(60)
        killpg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
