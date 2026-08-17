from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core import groups
from imports.models import ImportBatch, StagedPerson
from imports.parsing import parse_import_json

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def chairperson_user(db):
    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    return user


@pytest.fixture
def staged_batch(db):
    entries = parse_import_json((FIXTURES / "well_formed_import.json").read_bytes())
    batch = ImportBatch.objects.create(source_filename="well_formed_import.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    return batch


@pytest.mark.django_db
def test_a_chairperson_cannot_see_the_import_sidebar_link(client, chairperson_user):
    """The sidebar's section heading ("Import") renders regardless of
    permissions -- Unfold does this for every section, including "Records"
    and "Administration", which a chairperson-only user already cannot use
    either. What must actually be gated is the clickable item underneath,
    which carries the real URL and the real permission check.
    """
    client.force_login(chairperson_user)
    response = client.get(reverse("admin:index"))
    body = response.content.decode()
    assert "Profiling form import" not in body
    assert reverse("admin:imports_importbatch_changelist") not in body


@pytest.mark.django_db
def test_a_chairperson_cannot_reach_the_changelist(client, chairperson_user):
    client.force_login(chairperson_user)
    response = client.get(reverse("admin:imports_importbatch_changelist"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_reach_the_upload_screen(client, chairperson_user):
    client.force_login(chairperson_user)
    response = client.get(reverse("admin:imports_importbatch_upload"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_upload_a_file(client, chairperson_user):
    client.force_login(chairperson_user)
    upload = SimpleUploadedFile(
        "well_formed_import.json",
        (FIXTURES / "well_formed_import.json").read_bytes(),
        content_type="application/json",
    )
    response = client.post(reverse("admin:imports_importbatch_upload"), {"file": upload})
    assert response.status_code == 403
    assert ImportBatch.objects.count() == 0


@pytest.mark.django_db
def test_a_chairperson_cannot_view_batch_progress(client, chairperson_user, staged_batch):
    client.force_login(chairperson_user)
    response = client.get(
        reverse("admin:imports_importbatch_change", args=[staged_batch.pk])
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_reach_the_review_screen(client, chairperson_user, staged_batch):
    client.force_login(chairperson_user)
    row = staged_batch.rows.first()
    response = client.get(
        reverse("admin:imports_importbatch_review", args=[staged_batch.pk, row.pk])
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_approve_a_row_by_posting_directly(
    client, chairperson_user, staged_batch
):
    """Belt and suspenders: even a hand-crafted POST straight at the review
    URL, bypassing whatever the UI would normally show, must be refused."""
    client.force_login(chairperson_user)
    row = staged_batch.rows.first()
    response = client.post(
        reverse("admin:imports_importbatch_review", args=[staged_batch.pk, row.pk]),
        {"action": "approve"},
    )
    assert response.status_code == 403
    row.refresh_from_db()
    assert row.status == "PENDING"


@pytest.mark.django_db
def test_an_anonymous_user_cannot_reach_any_of_it(client, staged_batch):
    row = staged_batch.rows.first()
    urls = [
        reverse("admin:imports_importbatch_changelist"),
        reverse("admin:imports_importbatch_upload"),
        reverse("admin:imports_importbatch_change", args=[staged_batch.pk]),
        reverse("admin:imports_importbatch_review", args=[staged_batch.pk, row.pk]),
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url
