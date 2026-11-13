from django.core.files.storage import FileSystemStorage, storages
from django.core.management.base import BaseCommand, CommandError

from records.models import FormScan


class Command(BaseCommand):
    help = "Verify remote scan storage and read each referenced file without printing member data."

    def handle(self, *args, **options):
        if isinstance(storages["default"], FileSystemStorage):
            raise CommandError("Scans must use persistent remote storage in production.")
        checked = 0
        missing = 0
        for scan in FormScan.objects.exclude(file="").only("file").iterator():
            try:
                with scan.file.open("rb") as handle:
                    if not handle.read(1):
                        missing += 1
            except (FileNotFoundError, OSError):
                missing += 1
            checked += 1
        if missing:
            raise CommandError(f"{missing} of {checked} stored scans are missing, empty, or unreadable.")
        self.stdout.write(f"Verified remote scan storage: {checked} referenced files readable.")
