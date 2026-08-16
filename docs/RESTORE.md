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

Also set `PGPASSWORD` before running these non-interactively, or each
command will prompt for a password and appear to hang:

- PowerShell: `$env:PGPASSWORD = "aeci"`
- bash: `export PGPASSWORD=aeci`

## Restore into a scratch database

1. Create an empty database:
   `createdb -h localhost -U aeci aeci_restore_test`
2. Load the dump:
   `psql -h localhost -U aeci -d aeci_restore_test -f backups/aeci-YYYY-MM-DD-HHMM.sql`
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
6. Drop the scratch database: `dropdb -h localhost -U aeci aeci_restore_test`

## What backup_database guarantees (and what it does not)

- **Missing `pg_dump`** (bad `PG_DUMP_PATH`, or the binary genuinely absent):
  the command exits non-zero with a Python traceback (`FileNotFoundError`).
  It does not create a dump file.
- **Wrong database credentials**: `pg_dump` itself exits non-zero (auth
  failure), `subprocess.run(..., check=True)` raises `CalledProcessError`,
  and the management command exits non-zero with a traceback. The target
  `.sql` file may exist but will be empty or truncated — do not trust a
  dump written during a failed run.
- **Unwritable output directory**: `pg_dump` cannot open the target file,
  exits non-zero, and the command exits non-zero the same way.
- **Two backups in the same minute**: the filename only has minute
  resolution (`aeci-YYYY-MM-DD-HHMM.sql`). The command checks for an
  existing file with that name first and refuses to run rather than
  silently overwriting the earlier backup — it raises `CommandError` and
  exits non-zero.
- In every failure case above the process exits with a non-zero status and
  prints a traceback to stderr. None of them fail silently. If backups run
  on a schedule, alert on any non-zero exit from this command.

## Record the drill

Write the date and the row counts in this file. If the counts do not match
production, stop and investigate before trusting the backup.

| Date of drill | Person rows | Committee rows | Who ran it |
| --- | --- | --- | --- |
| 2026-08-17 | 0 | 12 | Claude Code, on behalf of goodinggoodjao@gmail.com (real dump loaded into a scratch DB; see task-13-report.md for the full transcript) |
