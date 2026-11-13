"""Restore a backup into a disposable local PostgreSQL database, never production.

DATABASE_URL remains the source. RESTORE_CHECK_DATABASE_URL must point to
the fresh local PostgreSQL service named aegis_restore_check in Actions.
"""
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

import psycopg


def restore_target(url):
    target = urlsplit(url)
    if (target.scheme not in {"postgres", "postgresql"}
            or target.hostname not in {"127.0.0.1", "localhost"}
            or target.path != "/aegis_restore_check"):
        raise ValueError("Restore target must be a local disposable aegis_restore_check database.")
    return target


def main():
    target_url = os.environ["RESTORE_CHECK_DATABASE_URL"]
    target = restore_target(target_url)
    backup = Path(sys.argv[1]).resolve(strict=True)
    with psycopg.connect(target_url) as connection:
        count = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        ).fetchone()[0]
        if count:
            raise ValueError("Restore target is not empty; refusing to overwrite any database.")
    env = {**os.environ, "PGHOST": target.hostname, "PGPORT": str(target.port or 5432),
           "PGDATABASE": "aegis_restore_check", "PGUSER": unquote(target.username or "postgres"),
           "PGPASSWORD": unquote(target.password or ""), "PGSSLMODE": "disable"}
    with tempfile.TemporaryDirectory(prefix="aegis-restore-") as scratch:
        sql = Path(scratch) / "restore.sql"
        with gzip.open(backup, "rb") as source, sql.open("wb") as output:
            shutil.copyfileobj(source, output)
        # Do not print restored SQL: it contains the full member register.
        result = subprocess.run(
            [os.environ.get("PSQL_PATH", "psql"), "-X", "-v", "ON_ERROR_STOP=1",
             "--single-transaction", "-f", str(sql)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError("Backup restore failed. SQL output suppressed to protect member data.")
    with psycopg.connect(target_url) as connection:
        for table in ["django_migrations", "auth_user", "people_person",
                      "committees_appointment", "records_formscan"]:
            count = connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table))
            ).fetchone()[0]
            if table == "django_migrations" and count == 0:
                raise RuntimeError("Restored backup has no migration history.")
            print(f"Restored {table}: {count} rows")
    print("Backup restore verified in a disposable local database.")


if __name__ == "__main__":
    main()
