from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core import groups
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
