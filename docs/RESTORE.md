# Restoring the AECI registry from a backup

A backup nobody has restored from is a rumour. Run this drill once before
go-live and once a year afterwards. Whoever runs it should be someone other
than the person who wrote the backup command, if possible.

## Before you start: find the PostgreSQL client tools

The commands below (`pg_dump`, `createdb`, `psql`, `dropdb`) all ship with
PostgreSQL, but a stock Windows install does **not** add its `bin` directory
to `PATH`. Two ways to deal with this:

- **Add it to PATH for the session** (PowerShell):
  `$env:PATH = "C:\Program Files\PostgreSQL\17\bin;$env:PATH"`
  then the commands below work as written.
- **Or prefix every command** with the full path, e.g.
  `"C:\Program Files\PostgreSQL\17\bin\createdb.exe"`.

The `backup_database` management command does not need this trick — it
reads the `PG_DUMP_PATH` setting (see `.env.example`), which defaults to the
bare `pg_dump` command and can be overridden with a full path in `.env`.
`createdb`/`psql`/`dropdb` in this drill are separate binaries from the same
install and are not covered by that setting, because they are run by a
human at a terminal, not by application code.

## Before you start: passwords and shell history

Setting `PGPASSWORD` (or typing any credential) at an interactive prompt
writes it to that shell's saved history:

- **PowerShell** saves every command you type via PSReadLine to a file on
  disk (`(Get-PSReadLineOption).HistorySavePath`, normally under
  `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\`) that survives after
  the window closes. `$env:PGPASSWORD = "the real production password"`
  puts that password in plaintext on disk, indefinitely, outside of any
  backup or access control you have on the database itself.
- bash has the same problem for `export PGPASSWORD=...` unless you
  configure `HISTCONTROL=ignorespace` and remember to prefix the line with
  a space.

Safer options, in order of preference:

1. Use a `.pgpass` file (`%APPDATA%\postgresql\pgpass.conf` on Windows,
   `~/.pgpass` — mode `0600` — on Linux) instead of `PGPASSWORD` at all.
   This is what the client tools check automatically; nothing sensitive
   ever touches the shell.
2. If you must type a password inline, disable history first:
   PowerShell — `Set-PSReadLineOption -HistorySaveStyle SaveNothing`;
   bash — `unset HISTFILE` for that session.
3. If you already typed one, delete it from the saved history file
   afterwards. Don't rely on `Clear-History` alone — it only clears the
   in-memory list, not the file PSReadLine already wrote to disk.

## Restore into a scratch database

1. Create an empty database:
   `createdb -h localhost -U aeci aeci_restore_test`
2. Load the dump. Backups are gzip-compressed (`aeci-YYYY-MM-DD-HHMM.sql.gz`).
   The cleanest option never writes a decompressed plaintext copy to disk at
   all — pipe the decompression straight into `psql`:
   - bash / Git Bash / WSL: `gunzip -c backups/aeci-YYYY-MM-DD-HHMM.sql.gz | psql -h localhost -U aeci -d aeci_restore_test`
   - Windows has no built-in `gunzip`. If you're not in a bash shell, decompress
     with Python (already a project dependency) instead of installing anything:
     `python -c "import gzip,shutil;shutil.copyfileobj(gzip.open('backups/aeci-YYYY-MM-DD-HHMM.sql.gz','rb'), open('restore.sql','wb'))"`
     then `psql -h localhost -U aeci -d aeci_restore_test -f restore.sql`
     — **and see step 5b below: that `restore.sql` is a full plaintext copy
     of the member register and must be deleted before you move on.**
3. Point a shell at it:
   `DATABASE_URL=postgres://aeci:aeci@localhost:5432/aeci_restore_test python manage.py shell`
4. Confirm the data survived:

```python
from people.models import Person
from committees.models import Committee
print(Person.objects.count(), Committee.objects.count())
```

5. Compare those counts against the source database (same query, without
   the `DATABASE_URL` override) — they must match exactly.
5b. **If you decompressed to a file in step 2, delete it now**:
   `rm restore.sql` (bash) or `Remove-Item restore.sql` (PowerShell). The
   drill is not finished until that plaintext copy of the register is
   gone — leaving it on disk defeats the point of backups living in
   access-controlled object storage instead of loose files. The gzip'd
   backup itself (`.sql.gz`) is fine to keep; it is what's covered by the
   file permission hardening the backup command already applies.
6. Drop the scratch database: `dropdb -h localhost -U aeci aeci_restore_test`

## What backup_database guarantees (and what it does not)

- **Missing `pg_dump`** (bad `PG_DUMP_PATH`, or the binary genuinely absent):
  the command exits non-zero with a Python traceback (`FileNotFoundError`).
  It does not create a dump file.
- **Wrong database credentials**: `pg_dump` itself exits non-zero (auth
  failure), `subprocess.run(..., check=True)` raises `CalledProcessError`,
  and the management command exits non-zero with a traceback.
- **Unwritable output directory**: `pg_dump` cannot open the target file,
  exits non-zero, and the command exits non-zero the same way.
- **A killed or otherwise-interrupted `pg_dump`**: it writes to a
  `.partial` file, never to the final name. On any failure the `.partial`
  file is deleted before the exception propagates. Nothing that looks like
  a finished backup (`aeci-*.sql.gz`) is ever left behind by a failed run.
- **Two backups in the same minute**: the filename only has minute
  resolution. The command checks for an existing *complete* backup
  (`aeci-YYYY-MM-DD-HHMM.sql.gz`) with that name and refuses to run rather
  than overwriting it — it raises `CommandError` and exits non-zero. Because
  the guard only looks for a complete backup, a failed attempt (which never
  produces one) can never block the retry that follows it in the same
  minute.
- In every failure case above the process exits with a non-zero status and
  prints a traceback to stderr. None of them fail silently. If backups run
  on a schedule, alert on any non-zero exit from this command.
- **Compression**: the dump is gzip-compressed after `pg_dump` finishes
  (roughly 8x smaller for this database).
- **Off-host storage**: when `BACKUP_TO_STORAGE=True` (defaults to
  whatever `USE_S3_STORAGE` is set to — production should have both on),
  the compressed dump is also uploaded through the same storage backend
  scan images use, under a `backups/` key prefix so the two never mingle.
  The command prints the storage key it used. When the setting is off
  (the local-development default), the dump stays local-only, same as
  before.
- **Retention**: after writing (and, if configured, uploading) a backup,
  the command deletes local and uploaded backups older than
  `BACKUP_RETENTION_DAYS` (default 30) — except the single newest one,
  which is never deleted even if it is itself older than the window. A
  stale backup beats no backup.
- **File permissions**: the backup directory and the finished dump have
  their permissions restricted after every run. On Linux this is `chmod
  700` (directory) / `600` (file) — authoritative, since `os.chmod` sets
  real POSIX permission bits. On Windows, `os.chmod` cannot do this (it
  only toggles the read-only attribute, not the ACL), so the command shells
  out to `icacls` instead, strips inherited permissions, and grants access
  only to the current user, `Administrators`, and `SYSTEM`. This is
  best-effort and only applies going forward — a backup written before this
  behaviour existed keeps whatever permissions it already had.

## The real disaster: the hosted database is gone

The scratch-database drill above proves a backup file is readable. It does
not prove you can bring the *church back online* from nothing. That drill
looks like this:

1. **Provision a fresh database.** If the host is Neon: create a new
   project/branch in the Neon console (or `neonctl projects create`) and
   copy its connection string. Neon connection strings require
   `sslmode=require` — keep that in the URL.
2. **Get the most recent backup.** If `BACKUP_TO_STORAGE` was on, it's in
   the object storage bucket under `backups/aeci-*.sql.gz` — the same
   R2/B2/S3-compatible bucket `USE_S3_STORAGE` points scan images at.
   Download it. If it was never uploaded (local-only mode), the only copy
   may be on whatever machine last ran the command — which is itself a
   reason to turn `BACKUP_TO_STORAGE` on before you need it.
3. **Restore into the new database** — same mechanics as the scratch drill,
   pointed at the real new database instead of a throwaway one:
   `gunzip -c aeci-YYYY-MM-DD-HHMM.sql.gz | psql "$NEW_DATABASE_URL"`
   (or the Python-decompress-then-`psql -f` variant on Windows — and delete
   the decompressed file afterward, as above).
4. **Repoint the app.** Update `DATABASE_URL` in the deployment host's
   environment configuration to the new connection string and redeploy.
   The `Procfile`'s `release: python manage.py migrate --noinput` phase
   will bring the restored schema up to date with any migrations added
   since the backup was taken.
5. **Verify before declaring recovery complete.** Compare `Person.objects.count()`
   and `Committee.objects.count()` (and anything else that matters) against
   the last row counts recorded in this file's drill table. A restore that
   "worked" but is missing weeks of data is not recovery.
6. **Remember the other half: scan images.** `FormScan.file` in the
   database only stores a *reference* (a storage key) — the actual scanned
   images live in the R2/B2 bucket, not in the SQL dump. Restoring the
   database without confirming that bucket is intact leaves every
   `FormScan` row pointing at files that may or may not exist. Recovering
   the register is two separate systems: the database dump (this
   document) and the object storage bucket's own durability (bucket
   versioning/replication — set that up on the bucket itself; it is not
   something this command does).

## Known gaps (deliberately out of scope here)

- **Scheduling.** Nothing runs `backup_database` automatically yet. Most
  free-tier hosts have no usable cron; wiring up a schedule belongs in
  [the deployment runbook](DEPLOYMENT.md), not this command.
- **The spec §8.4 admin spreadsheet export** is a separate reporting
  feature, not part of database backup/restore.

## Record the drill

Write the date and the row counts in this file. If the counts do not match
production, stop and investigate before trusting the backup.

| Date of drill | Person rows | Committee rows | Who ran it |
| --- | --- | --- | --- |
| 2026-08-17 | 0 | 12 | Claude Code, on behalf of goodinggoodjao@gmail.com — uncompressed dump; see task-13-report.md |
| 2026-08-17 | 0 | 12 | Claude Code, on behalf of goodinggoodjao@gmail.com — repeated against a **gzip-compressed** dump after fix round 1; see task-13-report.md |
