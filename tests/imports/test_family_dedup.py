"""CRITICAL 1: both parents' paper forms list the same children -- approving
the second parent's row must join the first parent's household, not build a
disconnected second one with duplicate child Person rows.

tests/imports/fixtures/family_shared_children.json holds two entries (a
husband and wife, same surname, same two children, each naming the other as
spouse_name) -- exactly the shape a real batch produces.
"""

from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import parse_import_json
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def family_batch(db):
    entries = parse_import_json((FIXTURES / "family_shared_children.json").read_bytes())
    batch = ImportBatch.objects.create(source_filename="family_shared_children.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    rows = {
        row.raw_data["first_name"]: row for row in StagedPerson.objects.filter(batch=batch)
    }
    return batch, rows


def _review_url(batch, row):
    return reverse("admin:imports_importbatch_review", args=[batch.pk, row.pk])


def _post_data(row):
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
def test_husband_then_wife_produces_one_household_and_two_children_not_two_and_four(
    client, secretariat_user, family_batch
):
    batch, rows = family_batch
    client.force_login(secretariat_user)

    husband = rows["MARK JEROME"]
    wife = rows["GLEAN"]

    response = client.post(_review_url(batch, husband), _post_data(husband))
    assert response.status_code == 302

    response = client.post(_review_url(batch, wife), _post_data(wife))
    assert response.status_code == 302

    # Exactly 4 real people: husband, wife, and the two children -- not the
    # 6 a naive approve-twice would create (2 parents + 4 duplicate kids).
    assert Person.objects.count() == 4
    assert Person.objects.filter(membership_status=MembershipStatus.CHILD).count() == 2
    assert Household.objects.count() == 1

    household = Household.objects.get()
    assert household.members.count() == 4
    roles = list(household.members.values_list("role", flat=True))
    assert roles.count(HouseholdRole.HEAD) == 1
    assert roles.count(HouseholdRole.SPOUSE) == 1
    assert roles.count(HouseholdRole.CHILD) == 2

    husband_person = Person.objects.get(last_name="JOSE", first_name="MARK JEROME")
    wife_person = Person.objects.get(last_name="JOSE", first_name="GLEAN")
    assert HouseholdMember.objects.filter(household=household, person=husband_person).exists()
    assert HouseholdMember.objects.filter(household=household, person=wife_person).exists()
    wife_membership = HouseholdMember.objects.get(household=household, person=wife_person)
    assert wife_membership.role == HouseholdRole.SPOUSE


@pytest.mark.django_db
def test_wife_then_husband_also_produces_one_household_and_two_children(
    client, secretariat_user, family_batch
):
    """Symmetric: order must not matter."""
    batch, rows = family_batch
    client.force_login(secretariat_user)

    husband = rows["MARK JEROME"]
    wife = rows["GLEAN"]

    client.post(_review_url(batch, wife), _post_data(wife))
    client.post(_review_url(batch, husband), _post_data(husband))

    assert Person.objects.count() == 4
    assert Person.objects.filter(membership_status=MembershipStatus.CHILD).count() == 2
    assert Household.objects.count() == 1


@pytest.mark.django_db
def test_linking_the_second_parent_is_reported_on_the_approval_result(
    client, secretariat_user, family_batch
):
    """Silent linking is as bad as silent duplication -- the reviewer must be
    told which existing records were reused."""
    batch, rows = family_batch
    client.force_login(secretariat_user)

    husband = rows["MARK JEROME"]
    wife = rows["GLEAN"]
    client.post(_review_url(batch, husband), _post_data(husband))

    response = client.post(_review_url(batch, wife), _post_data(wife), follow=True)
    body = response.content.decode()
    assert "Linked to existing child" in body
    assert "SHILOH" in body.upper()


@pytest.mark.django_db
def test_an_ambiguous_child_match_is_refused_not_guessed(client, secretariat_user, family_batch):
    """A name match with a *different* date of birth than the already-created
    child must not be silently treated as the same child, and must not
    silently create a second one either -- it is surfaced to the reviewer."""
    batch, rows = family_batch
    client.force_login(secretariat_user)

    husband = rows["MARK JEROME"]
    wife = rows["GLEAN"]
    client.post(_review_url(batch, husband), _post_data(husband))

    post = _post_data(wife)
    post["children-0-date_of_birth"] = "2016-02-26"  # one day off from the husband's entry
    response = client.post(_review_url(batch, wife), post)
    assert response.status_code == 200  # re-rendered, not redirected -- refused

    wife.refresh_from_db()
    assert wife.status == StagedPersonStatus.PENDING
    assert wife.error_message
    assert "SHILOH" in wife.error_message.upper()
    # Nothing partially written: no third child, no second household.
    assert Person.objects.filter(membership_status=MembershipStatus.CHILD).count() == 2
    assert Household.objects.count() == 1
