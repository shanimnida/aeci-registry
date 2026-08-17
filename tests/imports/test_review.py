from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import CommitteeMembership
from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import parse_import_json
from people.models import Household, HouseholdMember, MembershipStatus, Person
from records.models import AccessLog

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
    rows = StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    return batch, {row.raw_data["last_name"] + row.raw_data["first_name"]: row for row in StagedPerson.objects.filter(batch=batch)}


def _review_url(batch, row):
    return reverse("admin:imports_importbatch_review", args=[batch.pk, row.pk])


def _base_post_data(row):
    """A submission that changes nothing -- every field as the AI read it."""
    data = row.raw_data
    post = {
        "action": "approve",
        "member_no": data.get("member_no") or "",
        "last_name": data["last_name"],
        "first_name": data["first_name"],
        "middle_name": data.get("middle_name") or "",
        "suffix": data.get("suffix") or "",
        "date_of_birth": data.get("date_of_birth") or "",
        "place_of_birth": data.get("place_of_birth") or "",
        "gender": data.get("gender") or "",
        "civil_status": data.get("civil_status") or "",
        "nationality": data.get("nationality") or "",
        "home_address": data.get("home_address") or "",
        "mobile_number": data.get("mobile_number") or "",
        "email": data.get("email") or "",
        "spouse_name": data.get("spouse_name") or "",
        "date_of_marriage": data.get("date_of_marriage") or "",
        "form_version": data.get("form_version") or "v1",
        "date_filed": data.get("date_filed") or "",
        "certification_date": data.get("certification_date") or "",
        "emergency_contact_name": data.get("emergency_contact_name") or "",
        "emergency_relationship": data.get("emergency_relationship") or "",
        "emergency_number": data.get("emergency_number") or "",
        "committees": data.get("committees") or [],
        "membership_status": MembershipStatus.MEMBER,
        "notes": data.get("notes") or "",
        "children-TOTAL_FORMS": str(len(data.get("children") or [])),
        "children-INITIAL_FORMS": str(len(data.get("children") or [])),
        "children-MIN_NUM_FORMS": "0",
        "children-MAX_NUM_FORMS": "1000",
    }
    for index, child in enumerate(data.get("children") or []):
        post[f"children-{index}-full_name"] = child["full_name"]
        post[f"children-{index}-date_of_birth"] = child.get("date_of_birth") or ""
    return post


@pytest.mark.django_db
def test_approving_one_person_creates_exactly_that_person_household_children_and_committees(
    client, secretariat_user, staged_batch
):
    batch, rows = staged_batch
    row = rows["DELACRUZROSARIO"]  # has two children and one committee
    client.force_login(secretariat_user)

    post = _base_post_data(row)
    response = client.post(_review_url(batch, row), post)
    assert response.status_code == 302

    assert Person.objects.count() == 3  # the person + 2 children
    person = Person.objects.get(last_name="DELACRUZ", first_name="ROSARIO")
    assert person.membership_status == MembershipStatus.MEMBER
    assert person.mobile_number == "0917-123-9999"

    household = Household.objects.get()
    assert household.members.count() == 3
    child_names = set(
        Person.objects.filter(membership_status=MembershipStatus.CHILD).values_list(
            "first_name", "last_name"
        )
    )
    # _split_child_name (imports/services.py) strips the parent's own last
    # name off the end of the child's one-string full_name; the middle
    # initial has nowhere else to go, so it stays in first_name -- an
    # editable field the reviewer can tidy up before approving.
    assert ("MIKAELA ROSE P.", "DELACRUZ") in child_names
    assert ("GABRIEL JOHN P.", "DELACRUZ") in child_names

    memberships = CommitteeMembership.objects.filter(person=person)
    assert memberships.count() == 1
    assert memberships.get().committee.name == "Sunshine"

    row.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    assert row.created_person == person
    assert row.reviewed_by == secretariat_user
    assert row.reviewed_at is not None


@pytest.mark.django_db
def test_approving_a_person_who_ticked_three_committees_fails_validation_and_stays_pending(
    client, secretariat_user, staged_batch
):
    batch, rows = staged_batch
    row = rows["MANGUBATELENA"]  # three committees ticked
    client.force_login(secretariat_user)

    post = _base_post_data(row)
    assert len(post["committees"]) == 3
    response = client.post(_review_url(batch, row), post)
    assert response.status_code == 200  # re-rendered, not redirected

    assert Person.objects.count() == 0
    assert Household.objects.count() == 0
    assert CommitteeMembership.objects.count() == 0

    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING
    assert row.error_message  # a reason is recorded
    assert "two" in row.error_message.lower() or "2" in row.error_message

    body = response.content.decode()
    assert row.error_message in body


@pytest.mark.django_db
def test_a_reviewer_can_correct_a_field_before_approving(client, secretariat_user, staged_batch):
    """The fields are editable so the reviewer corrects rather than rejects
    -- proven here by dropping one of the three ticked committees so the
    person who would otherwise fail validation is approved instead."""
    batch, rows = staged_batch
    row = rows["MANGUBATELENA"]
    client.force_login(secretariat_user)

    post = _base_post_data(row)
    post["committees"] = ["Youth", "Food"]  # reviewer un-ticks ICT
    response = client.post(_review_url(batch, row), post)
    assert response.status_code == 302

    person = Person.objects.get(last_name="MANGUBAT")
    assert set(
        CommitteeMembership.objects.filter(person=person).values_list("committee__name", flat=True)
    ) == {"Youth", "Food"}

    row.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED


@pytest.mark.django_db
def test_v2_form_records_consent_v1_does_not(client, secretariat_user, staged_batch):
    batch, rows = staged_batch
    v1_row = rows["DELACRUZJUAN MIGUEL"]
    v2_row = rows["MANGUBATELENA"]
    client.force_login(secretariat_user)

    client.post(_review_url(batch, v1_row), _base_post_data(v1_row))
    person_v1 = Person.objects.get(last_name="DELACRUZ", first_name="JUAN MIGUEL")
    assert person_v1.consent_given is False

    post = _base_post_data(v2_row)
    post["committees"] = ["Youth"]
    client.post(_review_url(batch, v2_row), post)
    person_v2 = Person.objects.get(last_name="MANGUBAT")
    assert person_v2.consent_given is True
    assert person_v2.consent_date is not None


@pytest.mark.django_db
def test_a_blank_required_field_is_refused_by_the_form_without_touching_the_database(
    client, secretariat_user, staged_batch
):
    """Distinct from the CommitteeMembership.full_clean() failure above: this
    is Django's own form validation (last_name is a required form field),
    which must also leave the row pending and create nothing, not crash.
    """
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    post = _base_post_data(row)
    post["last_name"] = ""
    response = client.post(_review_url(batch, row), post)
    assert response.status_code == 200
    assert b"This field is required" in response.content or b"required" in response.content

    assert Person.objects.count() == 0
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING


@pytest.mark.django_db
def test_rejecting_a_person_creates_no_person_and_marks_the_row_rejected(
    client, secretariat_user, staged_batch
):
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    response = client.post(_review_url(batch, row), {**_base_post_data(row), "action": "reject"})
    assert response.status_code == 302

    row.refresh_from_db()
    assert row.status == StagedPersonStatus.REJECTED
    assert row.created_person is None
    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_skipping_does_not_change_the_row_and_moves_to_the_next_pending_entry(
    client, secretariat_user, staged_batch
):
    batch, rows = staged_batch
    first = StagedPerson.objects.filter(batch=batch).order_by("sequence").first()
    client.force_login(secretariat_user)

    response = client.post(_review_url(batch, first), {"action": "skip"})
    assert response.status_code == 302

    first.refresh_from_db()
    assert first.status == StagedPersonStatus.PENDING
    assert first.reviewed_by is None

    second = StagedPerson.objects.get(batch=batch, sequence=1)
    assert response.url == reverse("admin:imports_importbatch_review", args=[batch.pk, second.pk])


@pytest.mark.django_db
def test_stopping_and_resuming_a_batch_reaches_the_same_pending_rows(
    client, secretariat_user, staged_batch
):
    """The reviewer approves one, then "leaves" (no session state beyond the
    database), comes back later, and the batch's progress page still finds
    exactly the remaining pending rows -- nothing was lost by stopping."""
    batch, rows = staged_batch
    client.force_login(secretariat_user)

    first_row = StagedPerson.objects.filter(batch=batch).order_by("sequence").first()
    client.post(_review_url(batch, first_row), _base_post_data(first_row))

    # Simulate leaving and coming back: a fresh request to the batch's
    # progress page, not carrying anything from the review POST above.
    progress = client.get(reverse("admin:imports_importbatch_change", args=[batch.pk]))
    assert progress.status_code == 200
    assert batch.counts()["approved"] == 1
    assert batch.counts()["pending"] == 2

    remaining = StagedPerson.objects.filter(batch=batch, status=StagedPersonStatus.PENDING)
    assert remaining.count() == 2
    # Continuing from the progress page reaches a still-pending row.
    next_row = batch.next_pending()
    review = client.get(_review_url(batch, next_row))
    assert review.status_code == 200


@pytest.mark.django_db
def test_progress_page_renders_every_status_badge(client, secretariat_user, staged_batch):
    batch, rows = staged_batch
    client.force_login(secretariat_user)

    approved_row = rows["DELACRUZJUAN MIGUEL"]
    client.post(_review_url(batch, approved_row), _base_post_data(approved_row))

    rejected_row = rows["DELACRUZROSARIO"]
    client.post(_review_url(batch, rejected_row), {**_base_post_data(rejected_row), "action": "reject"})

    response = client.get(reverse("admin:imports_importbatch_change", args=[batch.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Approved" in body
    assert "Rejected" in body
    assert "Pending" in body
    assert batch.counts() == {"total": 3, "pending": 1, "approved": 1, "rejected": 1}


@pytest.mark.django_db
def test_reviewing_an_already_decided_row_is_read_only(client, secretariat_user, staged_batch):
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)
    client.post(_review_url(batch, row), {"action": "reject"})

    response = client.get(_review_url(batch, row))
    assert response.status_code == 200
    assert b"Approve" not in response.content


@pytest.mark.django_db
def test_viewing_a_pending_row_writes_an_access_log_entry(client, secretariat_user, staged_batch):
    """IMPORTANT 3: this screen renders the same class of personal data every
    Person view logs (people/admin.py) and used to log nothing at all. A
    still-pending row has no Person yet, so it logs against `report`."""
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    assert AccessLog.objects.count() == 0
    response = client.get(_review_url(batch, row))
    assert response.status_code == 200

    entry = AccessLog.objects.get()
    assert entry.user == secretariat_user
    assert entry.person is None
    assert entry.report  # exactly one of person/report -- see AccessLog.record
    assert "DELACRUZ" in entry.report.upper()


@pytest.mark.django_db
def test_approving_a_row_then_viewing_it_again_logs_against_the_created_person(
    client, secretariat_user, staged_batch
):
    """Once a row is approved, viewing it again is viewing that Person's own
    data -- the log should point at the real Person, like every other view
    of them does, not stay pinned to a label nobody can search for."""
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    client.post(_review_url(batch, row), _base_post_data(row))
    row.refresh_from_db()
    AccessLog.objects.all().delete()  # isolate the log write from re-viewing below

    client.get(_review_url(batch, row))
    entry = AccessLog.objects.get()
    assert entry.person == row.created_person
    assert entry.report == ""


@pytest.mark.django_db
def test_a_future_birth_date_is_refused_at_approval_and_leaves_the_row_pending(
    client, secretariat_user, staged_batch
):
    """IMPORTANT 4, exercised through the actual import path: a birth year
    the AI faithfully transcribed as written (docs/IMPORT_TEMPLATE.md rule 3)
    reaches the reviewer, but approving it as-is is refused, not silently
    accepted the way it used to be."""
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    client.force_login(secretariat_user)

    post = _base_post_data(row)
    post["date_of_birth"] = "2099-01-01"
    response = client.post(_review_url(batch, row), post)
    assert response.status_code == 200  # re-rendered, not redirected -- refused

    assert Person.objects.count() == 0
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING
    assert "future" in row.error_message.lower()


@pytest.mark.django_db
def test_a_possible_duplicate_is_shown_before_approving_not_after(
    client, secretariat_user, staged_batch
):
    """MINOR 8: the duplicate check used to fire only after the Person
    already existed. It must be visible on the review screen itself, before
    the reviewer clicks Approve."""
    batch, rows = staged_batch
    row = rows["DELACRUZJUAN MIGUEL"]
    # An existing Person who will read as a duplicate of this row.
    Person.objects.create(
        last_name=row.raw_data["last_name"],
        first_name=row.raw_data["first_name"],
        date_of_birth=row.raw_data["date_of_birth"],
    )
    client.force_login(secretariat_user)

    response = client.get(_review_url(batch, row))
    assert response.status_code == 200
    body = response.content.decode()
    assert "may duplicate an existing record" in body
