import subprocess

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_backup_writes_a_dump(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # pg_dump writes to the path given after -f
        target = cmd[cmd.index("-f") + 1]
        with open(target, "wb") as handle:
            handle.write(b"-- fake dump")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    call_command("backup_database", "--output-dir", str(tmp_path))

    dumps = list(tmp_path.glob("aeci-*.sql"))
    assert len(dumps) == 1
    # PG_DUMP_PATH defaults to the bare command name, but is overridable
    # (this machine's Postgres install does not put pg_dump on PATH) — so
    # assert against the configured value rather than a hardcoded string.
    assert calls and calls[0][0] == settings.PG_DUMP_PATH


@pytest.mark.django_db
def test_backup_fails_loudly_when_pg_dump_errors(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        call_command("backup_database", "--output-dir", str(tmp_path))


@pytest.mark.django_db
def test_backup_refuses_to_overwrite_a_same_minute_backup(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        target = cmd[cmd.index("-f") + 1]
        with open(target, "wb") as handle:
            handle.write(b"-- fake dump")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    call_command("backup_database", "--output-dir", str(tmp_path))

    # A second backup in the same minute would collide on the same filename
    # (the timestamp only has minute resolution). It must fail loudly
    # instead of silently overwriting the first backup.
    with pytest.raises(CommandError):
        call_command("backup_database", "--output-dir", str(tmp_path))

    dumps = list(tmp_path.glob("aeci-*.sql"))
    assert len(dumps) == 1
