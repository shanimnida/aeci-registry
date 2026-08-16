import gzip
import subprocess
from datetime import datetime

import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands.backup_database import (
    prune_local_backups,
    prune_storage_backups,
)

# Captured before any test monkeypatches subprocess.run, so the passthrough
# below always reaches the real implementation.
_REAL_SUBPROCESS_RUN = subprocess.run


def _patch_pg_dump(monkeypatch, on_pg_dump):
    """Route only the pg_dump call through on_pg_dump(cmd, kwargs).

    The command also shells out to icacls (Windows) to lock down
    permissions on the output directory and the finished dump. Those calls
    must reach the real subprocess.run so permission-hardening genuinely
    runs during tests too — only the pg_dump invocation itself is faked.
    """

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == settings.PG_DUMP_PATH:
            return on_pg_dump(cmd, kwargs)
        return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


def _succeeds(calls=None):
    def on_pg_dump(cmd, kwargs):
        if calls is not None:
            calls.append(cmd)
        target = cmd[cmd.index("-f") + 1]
        with open(target, "wb") as handle:
            handle.write(b"-- fake dump")
        return subprocess.CompletedProcess(cmd, 0)

    return on_pg_dump


def _errors_immediately(cmd, kwargs):
    raise subprocess.CalledProcessError(1, cmd)


def _dies_after_partial_write(cmd, kwargs):
    target = cmd[cmd.index("-f") + 1]
    with open(target, "wb") as handle:
        handle.write(b"-- truncated, pg_dump was killed here")
    raise subprocess.CalledProcessError(-9, cmd)


@pytest.mark.django_db
def test_backup_writes_a_compressed_dump(tmp_path, monkeypatch):
    calls = []
    _patch_pg_dump(monkeypatch, _succeeds(calls))

    call_command("backup_database", "--output-dir", str(tmp_path))

    dumps = list(tmp_path.glob("aeci-*.sql.gz"))
    assert len(dumps) == 1
    # PG_DUMP_PATH defaults to the bare command name, but is overridable
    # (this machine's Postgres install does not put pg_dump on PATH) — so
    # assert against the configured value rather than a hardcoded string.
    assert calls and calls[0][0] == settings.PG_DUMP_PATH
    # No uncompressed .sql or in-progress .partial file left behind.
    assert not list(tmp_path.glob("aeci-*.sql"))
    assert not list(tmp_path.glob("*.partial"))
    with gzip.open(dumps[0], "rb") as handle:
        assert handle.read() == b"-- fake dump"


@pytest.mark.django_db
def test_backup_fails_loudly_when_pg_dump_errors(tmp_path, monkeypatch):
    _patch_pg_dump(monkeypatch, _errors_immediately)
    with pytest.raises(subprocess.CalledProcessError):
        call_command("backup_database", "--output-dir", str(tmp_path))


@pytest.mark.django_db
def test_a_killed_dump_leaves_no_partial_or_final_file(tmp_path, monkeypatch):
    """Reproduces the review finding: kill pg_dump mid-run.

    A partial file gets written (pg_dump was making progress), then the
    process dies. The command must not leave that partial file, or
    anything matching the final aeci-*.sql / aeci-*.sql.gz name, behind —
    either would look like a real backup to the same-minute guard or to a
    human skimming the directory.
    """
    _patch_pg_dump(monkeypatch, _dies_after_partial_write)
    with pytest.raises(subprocess.CalledProcessError):
        call_command("backup_database", "--output-dir", str(tmp_path))

    assert not list(tmp_path.glob("aeci-*.sql"))
    assert not list(tmp_path.glob("aeci-*.sql.gz"))
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.django_db
def test_backup_refuses_to_overwrite_a_same_minute_backup(tmp_path, monkeypatch):
    _patch_pg_dump(monkeypatch, _succeeds())
    call_command("backup_database", "--output-dir", str(tmp_path))

    # A second backup in the same minute would collide on the same filename
    # (the timestamp only has minute resolution). It must fail loudly
    # instead of silently overwriting the first backup.
    with pytest.raises(CommandError):
        call_command("backup_database", "--output-dir", str(tmp_path))

    dumps = list(tmp_path.glob("aeci-*.sql.gz"))
    assert len(dumps) == 1


@pytest.mark.django_db
def test_a_failed_retry_does_not_trip_the_same_minute_guard(tmp_path, monkeypatch):
    """A failed run must never block the retry that follows it.

    Simulates: first attempt is killed (leaves no complete backup), second
    attempt in the same minute succeeds. The guard only recognises a
    *complete* backup (aeci-*.sql.gz), so it must not mistake the aftermath
    of the failure for one.
    """
    _patch_pg_dump(monkeypatch, _dies_after_partial_write)
    with pytest.raises(subprocess.CalledProcessError):
        call_command("backup_database", "--output-dir", str(tmp_path))

    _patch_pg_dump(monkeypatch, _succeeds())
    call_command("backup_database", "--output-dir", str(tmp_path))

    assert len(list(tmp_path.glob("aeci-*.sql.gz"))) == 1


@pytest.mark.django_db
def test_a_compression_failure_cleans_up_and_does_not_trip_the_guard(
    tmp_path, monkeypatch
):
    """pg_dump can succeed and compression can still fail partway (disk
    full, permission error). That must not leave a truncated file at the
    guarded gz_target name either, and must not block the retry."""
    _patch_pg_dump(monkeypatch, _succeeds())

    def dying_gzip_open(*args, **kwargs):
        raise OSError("disk full (simulated)")

    real_gzip_open = gzip.open
    monkeypatch.setattr(gzip, "open", dying_gzip_open)

    with pytest.raises(OSError):
        call_command("backup_database", "--output-dir", str(tmp_path))

    assert not list(tmp_path.glob("aeci-*.sql"))
    assert not list(tmp_path.glob("aeci-*.sql.gz"))
    assert not list(tmp_path.glob("*.partial"))

    monkeypatch.setattr(gzip, "open", real_gzip_open)
    call_command("backup_database", "--output-dir", str(tmp_path))

    assert len(list(tmp_path.glob("aeci-*.sql.gz"))) == 1


@pytest.mark.django_db
def test_backup_passes_sslmode_to_pg_dump(tmp_path, monkeypatch, settings):
    captured_env = {}

    def on_pg_dump(cmd, kwargs):
        captured_env.update(kwargs.get("env") or {})
        target = cmd[cmd.index("-f") + 1]
        with open(target, "wb") as handle:
            handle.write(b"-- fake dump")
        return subprocess.CompletedProcess(cmd, 0)

    _patch_pg_dump(monkeypatch, on_pg_dump)
    # Reassign the whole DATABASES dict (rather than mutating the nested
    # OPTIONS dict in place) so pytest-django's settings fixture can detect
    # and revert it after the test. A nested in-place mutation is invisible
    # to that revert mechanism — it would leak sslmode=require into every
    # test that runs afterwards, in this file and any collected after it,
    # and this machine's local Postgres has no SSL configured, so that
    # leak turns into ('server does not support SSL, but SSL was required')
    # connection failures far away from this test.
    settings.DATABASES = {
        **settings.DATABASES,
        "default": {
            **settings.DATABASES["default"],
            "OPTIONS": {
                **settings.DATABASES["default"].get("OPTIONS", {}),
                "sslmode": "require",
            },
        },
    }

    call_command("backup_database", "--output-dir", str(tmp_path))

    assert captured_env.get("PGSSLMODE") == "require"


@pytest.mark.django_db
def test_backup_uploads_to_storage_when_enabled(tmp_path, monkeypatch, settings):
    """Exercises the upload path against a real local storage backend — a
    FileSystemStorage aliased as "default", the same mechanism production
    uses for S3 — rather than mocking or calling a real S3 endpoint."""
    _patch_pg_dump(monkeypatch, _succeeds())

    upload_root = tmp_path / "uploaded"
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(upload_root)},
        },
    }
    settings.BACKUP_TO_STORAGE = True

    call_command("backup_database", "--output-dir", str(tmp_path / "local"))

    uploaded = list((upload_root / "backups").glob("aeci-*.sql.gz"))
    assert len(uploaded) == 1


@pytest.mark.django_db
def test_backup_does_not_upload_when_disabled(tmp_path, monkeypatch, settings):
    _patch_pg_dump(monkeypatch, _succeeds())

    upload_root = tmp_path / "uploaded"
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(upload_root)},
        },
    }
    settings.BACKUP_TO_STORAGE = False

    call_command("backup_database", "--output-dir", str(tmp_path / "local"))

    assert not upload_root.exists()


def test_prune_local_backups_keeps_the_newest_even_if_stale(tmp_path):
    now = datetime(2026, 8, 17, 12, 0)
    old1 = tmp_path / "aeci-2025-01-01-0000.sql.gz"
    old2 = tmp_path / "aeci-2025-06-01-0000.sql.gz"
    newest_but_still_stale = tmp_path / "aeci-2025-07-01-0000.sql.gz"
    for path in (old1, old2, newest_but_still_stale):
        path.write_bytes(b"gz")

    removed = prune_local_backups(tmp_path, retention_days=30, now=now)

    assert set(removed) == {old1, old2}
    assert not old1.exists()
    assert not old2.exists()
    # A stale backup beats no backup — the newest is kept regardless of age.
    assert newest_but_still_stale.exists()


def test_prune_local_backups_leaves_everything_inside_the_window(tmp_path):
    now = datetime(2026, 8, 17, 12, 0)
    recent = tmp_path / "aeci-2026-08-10-0000.sql.gz"
    recent.write_bytes(b"gz")

    removed = prune_local_backups(tmp_path, retention_days=30, now=now)

    assert removed == []
    assert recent.exists()


def test_prune_storage_backups_keeps_the_newest_even_if_stale(tmp_path):
    storage = FileSystemStorage(location=str(tmp_path))
    now = datetime(2026, 8, 17, 12, 0)
    storage.save("backups/aeci-2025-01-01-0000.sql.gz", ContentFile(b"a"))
    storage.save("backups/aeci-2025-07-01-0000.sql.gz", ContentFile(b"b"))

    removed = prune_storage_backups(storage, "backups", retention_days=30, now=now)

    assert removed == ["backups/aeci-2025-01-01-0000.sql.gz"]
    assert not storage.exists("backups/aeci-2025-01-01-0000.sql.gz")
    assert storage.exists("backups/aeci-2025-07-01-0000.sql.gz")
