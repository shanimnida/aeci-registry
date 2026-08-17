"""Redesign of the review screen (2026-08-17): the AI's free-text `notes`
blob is gone, `uncertain_fields` renders at the specific field instead of a
separate block, and the form is grouped into the same sections the printed
profiling form uses. See imports/templates/admin/imports/importbatch/
review.html and _field.html.

tests/imports/fixtures/well_formed_import.json's DELACRUZ ROSARIO row
(IMG_9002.jpg) carries one uncertain field (email); MANGUBAT ELENA
(IMG_9003.jpg) carries an uncertain `committees` flag from ticking three
boxes. Both also carry `notes` text from the AI that must not appear.
"""

from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from imports.models import ImportBatch, StagedPerson
from imports.parsing import parse_import_json

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def staged_rows(db):
    entries = parse_import_json((FIXTURES / "well_formed_import.json").read_bytes())
    batch = ImportBatch.objects.create(source_filename="well_formed_import.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    return batch, {row.raw_data["last_name"] + row.raw_data["first_name"]: row for row in StagedPerson.objects.filter(batch=batch)}


def _review_url(batch, row):
    return reverse("admin:imports_importbatch_review", args=[batch.pk, row.pk])


@pytest.mark.django_db
def test_the_ai_free_text_notes_no_longer_appear_anywhere_on_the_screen(
    client, secretariat_user, staged_rows
):
    batch, rows = staged_rows
    row = rows["DELACRUZROSARIO"]
    assert "smudged" in row.raw_data["notes"]  # sanity: the fixture really carries prose
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert "smudged" not in body
    assert "Notes from the AI" not in body
    assert 'name="notes"' not in body


@pytest.mark.django_db
def test_a_flagged_field_shows_its_marker_next_to_the_field_itself(
    client, secretariat_user, staged_rows
):
    """DELACRUZ ROSARIO's email is the fixture's uncertain field. The flag
    must render right at the email field, carrying what the AI read."""
    batch, rows = staged_rows
    row = rows["DELACRUZROSARIO"]
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert "AI unsure" in body
    # The flag must be part of the email field's own rendered block, not a
    # separate top-of-page list the reviewer has to cross-reference back to
    # the form -- so it is delimited between the email label and the next
    # field's label in document order.
    email_start = body.index('for="id_email"')
    next_field_start = body.index('for="id_spouse_name"')
    email_block = body[email_start:next_field_start]
    assert "AI unsure" in email_block
    assert "no email field filled in on the form" in email_block


@pytest.mark.django_db
def test_there_is_no_longer_a_separate_uncertain_fields_block(
    client, secretariat_user, staged_rows
):
    batch, rows = staged_rows
    row = rows["DELACRUZROSARIO"]
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert "Uncertain fields" not in body


@pytest.mark.django_db
def test_a_whole_section_flag_shows_for_the_over_ticked_committees(
    client, secretariat_user, staged_rows
):
    """MANGUBAT ELENA's committees are flagged as a whole (three boxes
    ticked); this is not one input, so it renders at the section heading."""
    batch, rows = staged_rows
    row = rows["MANGUBATELENA"]
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert "AI unsure" in body
    assert "form allows only two" in body


@pytest.mark.django_db
def test_confidence_is_a_small_marker_not_a_sentence(client, secretariat_user, staged_rows):
    batch, rows = staged_rows
    row = rows["DELACRUZROSARIO"]  # confidence: medium
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert "AI confidence: Medium" in body


@pytest.mark.django_db
def test_sections_appear_in_the_same_order_as_the_paper_form(
    client, secretariat_user, staged_rows
):
    batch, rows = staged_rows
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    # Scoped to the form itself -- the sidebar nav has its own "Committees"
    # link (committees app) that would otherwise false-positive-match.
    form_body = body[body.index('<form method="post"'):]
    personal = form_body.index("Personal information")
    contact = form_body.index(">Contact<")
    family = form_body.index(">Family<")
    committees = form_body.index(">Committees<")
    certification = form_body.index("Certification")
    assert personal < contact < family < committees < certification


@pytest.mark.django_db
def test_the_approve_skip_reject_actions_are_still_present_and_individual(
    client, secretariat_user, staged_rows
):
    """No bulk approval -- exactly one row's worth of decision buttons."""
    batch, rows = staged_rows
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    body = response.content.decode()
    assert 'value="approve"' in body
    assert 'value="skip"' in body
    assert 'value="reject"' in body
    assert "select all" not in body.lower()
    assert "bulk" not in body.lower()
