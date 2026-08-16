import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Dump the database with pg_dump. A church register cannot be "
        "reconstructed if lost. Spec section 8.4."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        stamp = timezone.localtime().strftime("%Y-%m-%d-%H%M")
        target = output_dir / f"aeci-{stamp}.sql"

        if target.exists():
            # The filename only has minute resolution. Overwriting a backup
            # silently is worse than failing loudly and asking for a retry.
            raise CommandError(
                f"{target} already exists — a backup already ran this "
                "minute. Wait a minute and retry, or pass a different "
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
            "-f", str(target),
        ]

        # Inherit the real environment. Replacing it outright would strip PATH,
        # and pg_dump would not be found on the host.
        subprocess.run(
            command, check=True, env={**os.environ, "PGPASSWORD": db["PASSWORD"]}
        )

        self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
        return str(target)
