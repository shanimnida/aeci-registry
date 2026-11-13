import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from records.models import FormScan, FormType


def test_scan_storage_check_rejects_local_disk():
    with pytest.raises(CommandError, match="persistent remote storage"):
        call_command("verify_scan_storage")


@pytest.mark.django_db
def test_scan_storage_check_fails_for_missing_scan(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    scan = FormScan(form_type=FormType.MEMBER_PROFILING)
    scan.file.save("synthetic.txt", ContentFile(b"synthetic scan"))
    call_command("verify_scan_storage")
    scan.file.storage.delete(scan.file.name)
    with pytest.raises(CommandError, match="missing, empty, or unreadable"):
        call_command("verify_scan_storage")
