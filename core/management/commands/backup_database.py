import gzip
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# aeci-2026-08-17-0105.sql.gz -> "2026-08-17-0105"
BACKUP_NAME_RE = re.compile(r"^aeci-(\d{4}-\d{2}-\d{2}-\d{4})\.sql\.gz$")


def _parse_backup_stamp(filename):
    """Extract the timestamp encoded in a backup filename, or None."""
    match = BACKUP_NAME_RE.match(filename)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d-%H%M")


def prune_local_backups(output_dir, retention_days, now=None):
    """Delete completed local backups older than retention_days.

    The single newest backup is never removed, even if it is itself older
    than the window — a stale backup beats no backup at all. Returns the
    list of Paths removed.
    """
    now = now or timezone.localtime().replace(tzinfo=None)
    cutoff = now - timedelta(days=retention_days)

    dated = []
    for path in Path(output_dir).glob("aeci-*.sql.gz"):
        stamp = _parse_backup_stamp(path.name)
        if stamp is not None:
            dated.append((stamp, path))
    if not dated:
        return []

    dated.sort(key=lambda pair: pair[0])
    newest = dated[-1][1]

    removed = []
    for stamp, path in dated:
        if path == newest:
            continue
        if stamp < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def prune_storage_backups(storage, prefix, retention_days, now=None):
    """Same rule as prune_local_backups, for objects under storage/prefix."""
    now = now or timezone.localtime().replace(tzinfo=None)
    cutoff = now - timedelta(days=retention_days)

    try:
        _, files = storage.listdir(prefix)
    except FileNotFoundError:
        return []

    dated = []
    for name in files:
        stamp = _parse_backup_stamp(name)
        if stamp is not None:
            dated.append((stamp, f"{prefix}/{name}"))
    if not dated:
        return []

    dated.sort(key=lambda pair: pair[0])
    newest = dated[-1][1]

    removed = []
    for stamp, key in dated:
        if key == newest:
            continue
        if stamp < cutoff:
            storage.delete(key)
            removed.append(key)
    return removed


def _restrict_permissions(path):
    """Best-effort: keep the register dump unreadable to other local accounts.

    On Linux this is authoritative — os.chmod sets the real POSIX mode bits,
    so 0o600 (files) / 0o700 (dirs) genuinely locks other local accounts out.

    On Windows, os.chmod only toggles the read-only attribute; it does not
    touch the ACL, so a second local account can still hold inherited Full
    Control (verified on this machine: a second account had exactly that
    before this fix). Shell out to icacls instead: strip inherited
    permissions and grant access only to the current user, Administrators,
    and SYSTEM, using well-known SIDs so this is language/locale-independent.
    """
    if os.name == "nt":
        is_dir = Path(path).is_dir()
        # (OI)(CI) — object-inherit / container-inherit — only means
        # anything on a directory ACE (so files created inside inherit the
        # same grant). Putting those flags on a *file* grant is invalid:
        # verified by hand that icacls then silently produces an ACE that
        # grants nobody access, including the owner — the file becomes
        # unreadable by everyone. Plain "F" is correct for a file.
        perm = "(OI)(CI)F" if is_dir else "F"
        owner = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{owner}:{perm}",
                "/grant:r",
                f"*S-1-5-32-544:{perm}",  # Administrators
                "/grant:r",
                f"*S-1-5-18:{perm}",  # SYSTEM
            ],
            check=False,
            capture_output=True,
        )
    else:
        os.chmod(path, 0o700 if Path(path).is_dir() else 0o600)


class Command(BaseCommand):
    help = (
        "Dump the database with pg_dump, compress it, and (when configured) "
        "upload it to object storage. A church register cannot be "
        "reconstructed if lost. Spec section 8.4."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        _restrict_permissions(output_dir)

        stamp = timezone.localtime().strftime("%Y-%m-%d-%H%M")
        sql_target = output_dir / f"aeci-{stamp}.sql"
        gz_target = output_dir / f"aeci-{stamp}.sql.gz"
        # pg_dump writes here first. Only a dump that exited 0 is renamed to
        # a name the same-minute guard below (and the retention pruner)
        # recognise — a killed or failed run must never leave something
        # that LOOKS like a finished backup.
        working = output_dir / f"aeci-{stamp}.sql.partial"
        # Same idea for compression: a disk-full or permission failure
        # partway through gzip must not leave a truncated file sitting at
        # the guarded gz_target name either.
        gz_working = output_dir / f"aeci-{stamp}.sql.gz.partial"

        if gz_target.exists():
            raise CommandError(
                f"{gz_target} already exists — a backup already completed "
                "this minute. Wait a minute and retry, or pass a different "
                "--output-dir."
            )

        db = settings.DATABASES["default"]
        command = [
            settings.PG_DUMP_PATH,
            "--no-owner",
            "--no-privileges",
            "-h", db["HOST"] or "localhost",
            "-p", str(db["PORT"] or 5432),
            "-U", db["USER"],
            "-d", db["NAME"],
            "-f", str(working),
        ]

        # Inherit the real environment. Replacing it outright would strip PATH,
        # and pg_dump would not be found on the host.
        env = {**os.environ, "PGPASSWORD": db["PASSWORD"]}
        sslmode = (db.get("OPTIONS") or {}).get("sslmode")
        if sslmode:
            # DATABASE_URL's sslmode is what protects the app's own
            # connections; a nightly dump that drops it would cross the
            # network on a weaker channel than everything else.
            env["PGSSLMODE"] = sslmode

        try:
            subprocess.run(command, check=True, env=env)
        except BaseException:
            working.unlink(missing_ok=True)
            raise

        try:
            working.replace(sql_target)
            with open(sql_target, "rb") as raw, gzip.open(gz_working, "wb") as compressed:
                shutil.copyfileobj(raw, compressed)
            gz_working.replace(gz_target)
        finally:
            # The uncompressed intermediate never needs to survive this
            # call, win or lose — it's regenerated from a fresh pg_dump on
            # retry, never reused. If gzip itself failed, this also clears
            # the truncated .gz.partial so it can't be mistaken for a
            # finished backup.
            sql_target.unlink(missing_ok=True)
            gz_working.unlink(missing_ok=True)

        _restrict_permissions(gz_target)

        self.stdout.write(self.style.SUCCESS(f"Wrote {gz_target}"))

        storage_key = None
        if getattr(settings, "BACKUP_TO_STORAGE", False):
            storage_key = self._upload(gz_target)
            self.stdout.write(
                self.style.SUCCESS(f"Uploaded to storage key {storage_key}")
            )

        retention_days = getattr(settings, "BACKUP_RETENTION_DAYS", 30)
        removed_local = prune_local_backups(output_dir, retention_days)
        if removed_local:
            self.stdout.write(
                f"Pruned {len(removed_local)} local backup(s) older than "
                f"{retention_days} days."
            )
        if storage_key is not None:
            removed_remote = prune_storage_backups(
                storages["default"], "backups", retention_days
            )
            if removed_remote:
                self.stdout.write(
                    f"Pruned {len(removed_remote)} uploaded backup(s) older "
                    f"than {retention_days} days."
                )

        return str(gz_target)

    def _upload(self, gz_target):
        storage = storages["default"]
        key = f"backups/{gz_target.name}"
        with gz_target.open("rb") as fh:
            return storage.save(key, File(fh))
