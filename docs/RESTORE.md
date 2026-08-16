# Restoring AEGIS from a backup

AEGIS is the Avdei Elohim Growth Information System — deployed as the
`aeci-registry` service on Render, database `aeci` on Neon. A backup nobody
has restored from is a rumour. Run this drill once before go-live and once a
year afterwards. Whoever runs it should be someone other than the person who
wrote the backup command, if possible.

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

**Version note**: your local `psql`/`pg_dump` should be at least as new as
whatever Postgres major version Neon runs for the `aeci` project (visible in
Neon's Connection Details / Settings page). The same rule that makes the
scheduled backup workflow pin a specific client version (see
`docs/DEPLOYMENT.md`, Section 10) applies here too — an older `pg_dump`
refuses outright to dump from a newer server.

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

This drill uses a **local** backup file — one still sitting in the
`backups/` folder where `backup_database` wrote it, not yet touched by
object storage. (If you're instead pulling a backup down from R2, read
"Getting a backup out of object storage without corrupting it" further down
first — downloaded files need an extra check that local files don't.)

1. Create an empty database:
   `createdb -h localhost -U aeci aeci_restore_test`
2. Load the dump. Backups are gzip-compressed
   (`aeci-YYYY-MM-DD-HHMM.sql.gz`). **Every restore command below includes
   `-v ON_ERROR_STOP=1`. Do not drop it.** `psql` without that flag keeps
   going after a failed statement and still exits 0 — a restore that
   silently dropped half the tables looks, from the exit code alone,
   identical to one that worked. With the flag, the first real error stops
   the whole restore and `psql` exits non-zero, which step 3 below checks
   for.
   - bash / Git Bash / WSL: `gunzip -c backups/aeci-YYYY-MM-DD-HHMM.sql.gz | psql -v ON_ERROR_STOP=1 -h localhost -U aeci -d aeci_restore_test`
   - Windows has no built-in `gunzip`. If you're not in a bash shell, decompress
     with Python (already a project dependency) instead of installing anything:
     `python -c "import gzip,shutil;shutil.copyfileobj(gzip.open('backups/aeci-YYYY-MM-DD-HHMM.sql.gz','rb'), open('restore.sql','wb'))"`
     then `psql -v ON_ERROR_STOP=1 -h localhost -U aeci -d aeci_restore_test -f restore.sql`
     — **and see step 6 below: that `restore.sql` is a full plaintext copy
     of the member register and must be deleted before you move on.**
3. **Check the exit code before doing anything else.**
   - bash: `echo $?` right after the `psql` command — anything other than
     `0` means the restore stopped partway through. Do not proceed to step 4
     as if it succeeded; read the error `psql` printed and fix the cause
     (usually a schema mismatch — see "Repoint the app" below about running
     `migrate` first) before retrying.
   - PowerShell: `$LASTEXITCODE` — same rule.
4. Point a shell at it:
   `DATABASE_URL=postgres://aeci:aeci@localhost:5432/aeci_restore_test python manage.py shell`
5. **Verify against expected counts, not just "does a number show up."**
   Before you run this, know what the number *should* be — either the row
   counts recorded in this file's drill table below from the last successful
   drill, or a fresh count against the source database (same query, without
   the `DATABASE_URL` override) taken right before you started. Then:

   ```python
   from people.models import Person
   from committees.models import Committee
   print(Person.objects.count(), Committee.objects.count())
   ```

   If either number is lower than expected, the restore is incomplete even
   though `psql` exited 0 in step 3 — `ON_ERROR_STOP` catches SQL errors, not
   a dump that was already missing data when it was taken. Stop and
   investigate; do not record this drill as a pass.
6. **If you decompressed to a file in step 2, delete it now**:
   `rm restore.sql` (bash) or `Remove-Item restore.sql` (PowerShell). The
   drill is not finished until that plaintext copy of the register is
   gone — leaving it on disk defeats the point of backups living in
   access-controlled object storage instead of loose files. The gzip'd
   backup itself (`.sql.gz`) is fine to keep; it is what's covered by the
   file permission hardening the backup command already applies.
7. Drop the scratch database: `dropdb -h localhost -U aeci aeci_restore_test`

## Getting a backup out of object storage without corrupting it

**Every object `backup_database` uploads to R2 is stored with
`Content-Encoding: gzip` set on it — confirmed in the installed
`django-storages` package (`storages/backends/s3.py`,
`_get_write_parameters`): Python's `mimetypes.guess_type()` recognises the
`.gz` suffix on `aeci-YYYY-MM-DD-HHMM.sql.gz` as gzip encoding, and
django-storages copies that straight into the object's `ContentEncoding`
metadata on upload.** That header is a standard HTTP instruction: a client
that honours it — a web browser, the R2 dashboard's own "Download" button, a
presigned-URL fetch through `curl`'s default behaviour or Python's
`requests` — decompresses the object automatically while downloading it.
What lands on your disk is already plain SQL text, still named
`....sql.gz`. Running `gunzip` on that produces "not in gzip format" and
aborts — at exactly the moment you need the backup most.

**Check before you decompress, every time**, because which case you're in
depends on how you downloaded it:

- bash / Git Bash / WSL: `file aeci-YYYY-MM-DD-HHMM.sql.gz`. A real gzip file
  reports `gzip compressed data`; already-decompressed text reports `ASCII
  text` (or similar).
- PowerShell: `Format-Hex -Path aeci-YYYY-MM-DD-HHMM.sql.gz -Count 2` — a
  real gzip file starts with the two bytes `1F 8B`. Plain SQL text won't.
- **If it's already plain text**: skip `gunzip` entirely and feed the file
  straight to `psql -v ON_ERROR_STOP=1 -f`.
- **If it's still gzip-compressed** (you used a tool that preserves raw
  object bytes instead of following `Content-Encoding` — the AWS CLI's
  `aws s3 cp`, `rclone`, or a script calling `get_object` directly all do
  this): `gunzip` it first, exactly as in the scratch-database drill above,
  then feed the result to `psql -v ON_ERROR_STOP=1`.

Getting this backwards — gunzipping a file that's already plain text, or
feeding still-compressed bytes straight to `psql` — fails immediately and
obviously (a decompression error, or `psql` complaining the input isn't
SQL). The dangerous version of this mistake is assuming you know which case
you're in without checking; check every time, especially under pressure.

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
  prints a traceback to stderr. **None of them fail silently — but nothing
  in this project currently watches for that non-zero exit and tells a
  human.** The command doing its part (failing loudly) and someone actually
  finding out are two different things; see "Known gaps" below for the
  honest state of the second one.
- **Compression**: the dump is gzip-compressed after `pg_dump` finishes
  (roughly 8x smaller for this database).
- **Off-host storage**: when `BACKUP_TO_STORAGE=True` (defaults to
  whatever `USE_S3_STORAGE` is set to — production should have both on),
  the compressed dump is also uploaded through the same storage backend
  scan images use, under a `backups/` key prefix. That prefix keeps the two
  kinds of file from colliding by name; it is **not** an access boundary —
  see "One bucket, one credential" below. When the setting is off (the
  local-development default), the dump stays local-only, same as before.
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

## One bucket, one credential

Database backups and members' scanned paper forms are **not** isolated from
each other. Both live in the same Cloudflare R2 bucket, and the R2 API token
used to reach it (`docs/DEPLOYMENT.md`, Section 9) is scoped to that whole
bucket, not to the `backups/` prefix specifically. Anything holding that one
credential — the Render service, the GitHub Actions workflow — can read and
write both the full SQL dumps (name, birthdate, address, civil status,
everything in the register) and every scanned paper form. If that credential
leaks, both are exposed together; there is no scenario where only one of
them is at risk. Real separation would mean a second R2 bucket with its own
API token used only for backups, wired into a second Django storage backend
in `aeci/settings.py` — that's a code change, not something either
deployment document does today. Until it exists, treat the R2 credential
with the same care as the database password: it protects both.

## The real disaster: the hosted database is gone

The scratch-database drill above proves a backup file is readable. It does
not prove you can bring the *church back online* from nothing. That drill
looks like this:

1. **Provision a fresh database.** Create a new project/branch in the Neon
   console (or `neonctl projects create`) and copy its connection string.
   Neon connection strings require `sslmode=require` — keep that in the
   URL.
2. **Get the most recent backup and check whether it's still compressed**
   before you do anything else with it — see "Getting a backup out of
   object storage without corrupting it" above. If `BACKUP_TO_STORAGE` was
   on, it's in the R2 bucket under `backups/aeci-*.sql.gz`. If it was never
   uploaded (local-only mode), the only copy may be on whatever machine last
   ran the command — which is itself a reason to turn `BACKUP_TO_STORAGE` on
   before you need it (see `docs/DEPLOYMENT.md` Section 10, Option B, for
   how easy this is to get wrong even when you think you've set it).
3. **Restore into the new database** — same mechanics as the scratch drill,
   `-v ON_ERROR_STOP=1` and all, pointed at the real new database instead of
   a throwaway one:
   `gunzip -c aeci-YYYY-MM-DD-HHMM.sql.gz | psql -v ON_ERROR_STOP=1 "$NEW_DATABASE_URL"`
   (or the Python-decompress-then-`psql -v ON_ERROR_STOP=1 -f` variant on
   Windows — and delete the decompressed file afterward, as above). **Check
   the exit code** exactly as in scratch-drill step 3 before treating this
   as done.
4. **Repoint the app.** Update `DATABASE_URL` in the deployment host's
   environment configuration to the new connection string and redeploy.
   Render's Build Command includes `python manage.py migrate --noinput`
   (`docs/DEPLOYMENT.md`, Section 4), so the next deploy brings the restored
   schema up to date with any migrations added since the backup was taken.
5. **Verify before declaring recovery complete — against expected numbers,
   not just any numbers.** Compare `Person.objects.count()` and
   `Committee.objects.count()` (and anything else that matters) against the
   last row counts recorded in this file's drill table. A restore that
   "worked," exited 0, and is still missing weeks of data is not recovery —
   it is the scratch-drill step 5 warning, at full production stakes.
6. **Remember the other half: scan images.** `FormScan.file` in the
   database only stores a *reference* (a storage key) — the actual scanned
   images live in the R2 bucket, not in the SQL dump. Restoring the
   database without confirming that bucket is intact leaves every
   `FormScan` row pointing at files that may or may not exist. Recovering
   the register is two separate systems: the database dump (this document)
   and the object storage bucket's own durability (bucket
   versioning/replication — set that up on the bucket itself; it is not
   something this command does).

## Known gaps (deliberately out of scope here)

- **Scheduling.** Nothing runs `backup_database` automatically yet. Most
  free-tier hosts have no usable cron; wiring up a schedule belongs in
  [the deployment runbook](DEPLOYMENT.md), not this command.
- **Alerting.** Even once the schedule from the deployment runbook is set
  up, **nothing tells anyone if the nightly backup job stops running or
  starts failing.** The command itself never fails silently — see "What
  backup_database guarantees" above — but a GitHub Actions failure that
  nobody looks at is invisible in practice. This was never implemented,
  full stop; it is not a "coming soon," it is a real, current gap. The
  simplest honest mitigation right now is checking the repository's
  **Actions** tab by hand on some regular cadence (weekly is reasonable for
  a church this size); the next step up, if that ever proves unreliable, is
  a free "dead man's switch" ping (healthchecks.io, cronitor.io, or similar)
  added as one more step in the workflow — see `docs/DEPLOYMENT.md` Section
  10 for exactly what that would look like. Neither is implemented today.
- **The spec §8.4 admin spreadsheet export** is a separate reporting
  feature, not part of database backup/restore.

## Record the drill

Write the date and the row counts in this file. If the counts do not match
production, stop and investigate before trusting the backup.

| Date of drill | Person rows | Committee rows | Who ran it |
| --- | --- | --- | --- |
| 2026-08-17 | 0 | 12 | Claude Code, on behalf of goodinggoodjao@gmail.com — uncompressed dump; see task-13-report.md |
| 2026-08-17 | 0 | 12 | Claude Code, on behalf of goodinggoodjao@gmail.com — repeated against a **gzip-compressed** dump after fix round 1; see task-13-report.md |
