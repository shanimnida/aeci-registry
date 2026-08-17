import json
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core import groups
from imports.forms import MAX_IMPORT_FILE_SIZE
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from people.models import Person

FIXTURES = Path(__file__).parent / "fixtures"


def _upload(name):
    return SimpleUploadedFile(name, (FIXTURES / name).read_bytes(), content_type="application/json")


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.mark.django_db
def test_a_well_formed_file_stages_the_right_number_of_people_and_creates_no_person(
    client, secretariat_user
):
    client.force_login(secretariat_user)
    response = client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("well_formed_import.json")},
    )
    assert response.status_code == 302

    assert ImportBatch.objects.count() == 1
    batch = ImportBatch.objects.get()
    assert batch.rows.count() == 3
    assert batch.rows.filter(status=StagedPersonStatus.PENDING).count() == 3
    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_uploader_is_recorded_on_the_batch(client, secretariat_user):
    client.force_login(secretariat_user)
    client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("well_formed_import.json")},
    )
    batch = ImportBatch.objects.get()
    assert batch.uploaded_by == secretariat_user
    assert batch.source_filename == "well_formed_import.json"


@pytest.mark.django_db
def test_a_malformed_file_is_rejected_with_a_clear_message_and_stages_nothing(
    client, secretariat_user
):
    client.force_login(secretariat_user)
    response = client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("malformed_syntax.json")},
    )
    assert response.status_code == 200  # re-rendered with errors, no redirect
    body = response.content.decode()
    assert "not valid JSON" in body

    assert ImportBatch.objects.count() == 0
    assert StagedPerson.objects.count() == 0
    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_a_bad_shape_file_names_the_offending_entry_and_stages_nothing(
    client, secretariat_user
):
    client.force_login(secretariat_user)
    response = client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("bad_shape.json")},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "IMG_9020.jpg" in body

    assert ImportBatch.objects.count() == 0
    assert StagedPerson.objects.count() == 0


@pytest.mark.django_db
def test_an_oversized_file_is_refused_with_a_clear_message_not_a_crash(client, secretariat_user):
    """IMPORTANT 5: no cap used to exist at all, and imports/admin.py read
    the whole file into memory before decoding it."""
    client.force_login(secretariat_user)
    # Valid JSON shape (an array of one blank string) padded past the cap --
    # the point is the size check refuses it before parsing even starts.
    padding = "x" * (MAX_IMPORT_FILE_SIZE + 1)
    oversized = SimpleUploadedFile(
        "huge.json", padding.encode(), content_type="application/json"
    )
    response = client.post(
        reverse("admin:imports_importbatch_upload"), {"file": oversized}
    )
    assert response.status_code == 200  # re-rendered with a form error, no crash
    body = response.content.decode()
    assert "larger than AEGIS accepts" in body

    assert ImportBatch.objects.count() == 0
    assert StagedPerson.objects.count() == 0


@pytest.mark.django_db
def test_reuploading_the_same_file_warns_but_still_stages_it(client, secretariat_user):
    """IMPORTANT 7: warn, do not hard-block -- a genuine corrected re-upload
    of the same filename (or same content) is legitimate."""
    client.force_login(secretariat_user)
    client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("well_formed_import.json")},
    )
    assert ImportBatch.objects.count() == 1

    response = client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("well_formed_import.json")},
        follow=True,
    )
    # Non-blocking: the second upload still stages a second batch.
    assert ImportBatch.objects.count() == 2
    warnings = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("matches a previous import" in m for m in warnings)


@pytest.mark.django_db
def test_a_genuinely_different_file_is_not_flagged_as_a_reupload(client, secretariat_user):
    client.force_login(secretariat_user)
    client.post(
        reverse("admin:imports_importbatch_upload"),
        {"file": _upload("well_formed_import.json")},
    )
    entries = json.loads((FIXTURES / "well_formed_import.json").read_bytes().decode())
    entries[0]["notes"] = "a genuinely different file"
    different = SimpleUploadedFile(
        "well_formed_import.json", json.dumps(entries).encode(), content_type="application/json"
    )
    response = client.post(
        reverse("admin:imports_importbatch_upload"), {"file": different}, follow=True
    )
    warnings = [str(m) for m in get_messages(response.wsgi_request)]
    assert not any("matches a previous import" in m for m in warnings)


@pytest.mark.django_db
def test_the_upload_screen_renders_for_a_logged_in_secretariat_user(client, secretariat_user):
    client.force_login(secretariat_user)
    response = client.get(reverse("admin:imports_importbatch_upload"))
    assert response.status_code == 200
    assert b"Upload" in response.content


@pytest.mark.django_db
def test_the_upload_screen_requires_login(client):
    response = client.get(reverse("admin:imports_importbatch_upload"))
    assert response.status_code in (302, 403)
    if response.status_code == 302:
        assert "login" in response.url
