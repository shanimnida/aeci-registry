"""Redesign of the import review screens (2026-08-17): a volunteer holds one
physical form and must land on its on-screen entry in seconds -- upload
order is not pile order. This covers the search box on the batch's row list
(imports/admin.py's change_view / progress.html) and the "at a glance, what
is still pending" status tabs alongside it.

tests/imports/fixtures/well_formed_import.json holds three entries:
DELACRUZ, JUAN MIGUEL (IMG_9001.jpg), DELACRUZ, ROSARIO (IMG_9002.jpg,
uncertain email), and MANGUBAT, ELENA (IMG_9003.jpg, uncertain/over-ticked
committees).
"""

from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import parse_import_json

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def staged_batch(db):
    entries = parse_import_json((FIXTURES / "well_formed_import.json").read_bytes())
    batch = ImportBatch.objects.create(source_filename="well_formed_import.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    return batch


def _list_url(batch, **params):
    url = reverse("admin:imports_importbatch_change", args=[batch.pk])
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


@pytest.mark.django_db
def test_searching_by_full_surname_finds_that_family_and_excludes_others(
    client, secretariat_user, staged_batch
):
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="DELACRUZ"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" not in body


@pytest.mark.django_db
def test_searching_by_partial_lowercase_surname_still_finds_it(
    client, secretariat_user, staged_batch
):
    """Forgiving on purpose: case-insensitive and partial, since a volunteer
    types a surname off a handwritten sheet, not a database key."""
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="delac"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" not in body


@pytest.mark.django_db
def test_searching_by_source_image_filename_finds_only_that_row(
    client, secretariat_user, staged_batch
):
    """"someone comparing against a photo filename will type digits" --
    searching the numeric part of an image filename must work on its own,
    without the IMG_ prefix or the extension."""
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="9002"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "ROSARIO DELACRUZ" in body
    assert "JUAN MIGUEL DELACRUZ" not in body
    assert "ELENA MANGUBAT" not in body


@pytest.mark.django_db
def test_search_ignores_punctuation_and_spacing(client, secretariat_user, staged_batch):
    """A search typed with punctuation or spacing that is not in the
    underlying data must still match -- and vice versa."""
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="IMG-9002.jpg"))
    body = response.content.decode()
    assert "ROSARIO DELACRUZ" in body


@pytest.mark.django_db
def test_a_search_with_no_matches_says_so_without_erroring(
    client, secretariat_user, staged_batch
):
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="nosuchname"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" not in body
    assert "ROSARIO DELACRUZ" not in body
    assert "ELENA MANGUBAT" not in body
    assert "No entry matches" in body


@pytest.mark.django_db
def test_status_filter_shows_only_pending_rows_with_a_live_count(
    client, secretariat_user, staged_batch
):
    """"a way to see, at a glance, which rows are still pending" -- the
    Pending tab must both filter the list and carry the right count."""
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, status="PENDING"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Pending 3" in body
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" in body


@pytest.mark.django_db
def test_status_filter_updates_after_a_row_is_decided(client, secretariat_user, staged_batch):
    client.force_login(secretariat_user)
    row = StagedPerson.objects.get(batch=staged_batch, sequence=0)
    row.status = StagedPersonStatus.APPROVED
    row.save()

    response = client.get(_list_url(staged_batch, status="APPROVED"))
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" not in body
    assert "ELENA MANGUBAT" not in body

    pending_response = client.get(_list_url(staged_batch, status="PENDING"))
    pending_body = pending_response.content.decode()
    assert "Pending 2" in pending_body
    assert "JUAN MIGUEL DELACRUZ" not in pending_body


@pytest.mark.django_db
def test_search_and_status_filter_combine(client, secretariat_user, staged_batch):
    client.force_login(secretariat_user)
    response = client.get(_list_url(staged_batch, q="DELACRUZ", status="PENDING"))
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" not in body
