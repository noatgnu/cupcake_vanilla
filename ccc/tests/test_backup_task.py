"""
Tests for the backup task: it must copy the files dbbackup and mediabackup write into the
dbbackup storage location, and fail when a run produces no files.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ccc.models import BackupLog
from ccc.tasks import run_backup


class RunBackupTaskTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.backup_dir = Path(temp.name) / "backups"
        self.backup_dir.mkdir()
        self.destination = Path(temp.name) / "destination"

        storages_patch = patch("ccc.tasks.storages", {"dbbackup": MagicMock(location=str(self.backup_dir))})
        storages_patch.start()
        self.addCleanup(storages_patch.stop)

    def _log(self, backup_type):
        return BackupLog.objects.create(backup_type=backup_type, destination=str(self.destination))

    def _writes(self, names):
        """Fake dbbackup/mediabackup, writing one file per command into the backup directory."""
        outputs = dict(names)

        def call_command(name, *args, **kwargs):
            (self.backup_dir / outputs[name]).write_bytes(b"x" * 10)

        return call_command

    def test_full_backup_copies_only_the_files_this_run_wrote(self):
        old = self.backup_dir / "default-2026-01-01.psql.bin"
        old.write_bytes(b"old")
        os.utime(old, (0, 0))
        log = self._log("full")

        fake = self._writes({"dbbackup": "default-2026-10-29.psql.bin", "mediabackup": "media-2026-10-29.tar"})
        with patch("ccc.tasks.call_command", side_effect=fake):
            run_backup(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, "completed", log.error_message)
        self.assertEqual(
            sorted(p.name for p in self.destination.iterdir()),
            [
                "default-2026-10-29.psql.bin",
                "media-2026-10-29.tar",
            ],
        )
        self.assertEqual(log.size_bytes, 20)

    def test_database_backup_runs_only_dbbackup(self):
        log = self._log("database")
        fake = self._writes({"dbbackup": "default-2026-10-29.psql.bin"})
        with patch("ccc.tasks.call_command", side_effect=fake) as mock_command:
            run_backup(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, "completed", log.error_message)
        self.assertEqual([call.args[0] for call in mock_command.call_args_list], ["dbbackup"])
        self.assertEqual([p.name for p in self.destination.iterdir()], ["default-2026-10-29.psql.bin"])

    def test_backup_that_writes_nothing_fails(self):
        (self.backup_dir / "default-2026-01-01.psql.bin").write_bytes(b"old")
        log = self._log("full")

        with patch("ccc.tasks.call_command"):
            run_backup(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, "failed")
        self.assertIn("produced no files", log.error_message)
        self.assertFalse(any(self.destination.iterdir()))
