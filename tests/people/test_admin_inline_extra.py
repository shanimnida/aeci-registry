"""The blank-inline trap a volunteer reported: "if i were to save theres
always an error wherein an empty household field is added therefore i have
to delete that field so i can save."

HouseholdMemberInline and CommitteeMembershipInline both used to set
extra = 1, so every Person change form rendered one blank row whose fields
become required the moment it is touched at all -- even just clicking into
the household autocomplete. The volunteer's only way out was ticking
Delete on a row they never meant to create.

Fix: extra = 0 on every TabularInline in the project (people/admin.py's
three, matching committees/admin.py's CommitteeFunctionInline and
people/admin.py's own FormScanInline, both already 0). No inline is
rendered at all until someone explicitly clicks "Add another".

The reported error itself could not be reproduced -- posting the change
form back completely unchanged already succeeded before this fix, verified
by test below. What is verified here is narrower and stated plainly: the
trap (a blank row rendered by default) is gone, saving unchanged still
works with and without an existing household, and adding a household or a
committee membership still works with extra = 0.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.admin import CommitteeMembershipInline, HouseholdMemberInline, HouseholdPersonInline
from people.models import Household, HouseholdMember, HouseholdRole, Person

TODAY = dt.date(2026, 8, 22)


@pytest.fixture
def secretariat_client(client, db):
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    client.force_login(user)
    return client


def _inline_management_fields():
    """No inline is rendered by default under extra = 0 -- every formset
    starts at TOTAL_FORMS = 0, INITIAL_FORMS = 0."""
    fields = {}
    for prefix in ("household_memberships", "committee_memberships", "scans"):
        fields[f"{prefix}-TOTAL_FORMS"] = "0"
        fields[f"{prefix}-INITIAL_FORMS"] = "0"
        fields[f"{prefix}-MIN_NUM_FORMS"] = "0"
        fields[f"{prefix}-MAX_NUM_FORMS"] = "1000"
    return fields


def _person_post_data(person, **overrides):
    """Every non-inline field on the change form, exactly as it reads for
    `person` -- an unchanged resubmission."""
    data = {
        "member_no": person.member_no or "",
        "last_name": person.last_name,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "suffix": person.suffix,
        "nickname": person.nickname,
        "date_of_birth": person.date_of_birth.isoformat() if person.date_of_birth else "",
        "place_of_birth": person.place_of_birth,
        "gender": person.gender,
        "civil_status": person.civil_status,
        "nationality": person.nationality,
        "home_address": person.home_address,
        "mobile_number": person.mobile_number,
        "email": person.email,
        "emergency_contact_name": person.emergency_contact_name,
        "emergency_contact_relationship": person.emergency_contact_relationship,
        "emergency_contact_number": person.emergency_contact_number,
        "guardian": person.guardian_id or "",
        "guardian_relationship": person.guardian_relationship,
        "membership_status": person.membership_status,
        "date_filed": person.date_filed.isoformat() if person.date_filed else "",
        "date_became_member": person.date_became_member.isoformat() if person.date_became_member else "",
        "approved_by": person.approved_by_id or "",
        "date_of_death": person.date_of_death.isoformat() if person.date_of_death else "",
        "consent_date": person.consent_date.isoformat() if person.consent_date else "",
        "consent_version": person.consent_version,
        "follow_up_notes": person.follow_up_notes,
        "notes": person.notes,
    }
    data.update(_inline_management_fields())
    data.update(overrides)
    return data


# -- the trap itself: no inline renders a blank row -----------------------


def test_every_tabular_inline_in_the_project_is_extra_zero():
    """CommitteeFunctionInline (committees/admin.py) and FormScanInline
    were already extra = 0 -- HouseholdMemberInline, CommitteeMembershipInline
    and HouseholdPersonInline (the same rows, seen from the Household side)
    are the ones this bug fixes."""
    assert HouseholdMemberInline.extra == 0
    assert CommitteeMembershipInline.extra == 0
    assert HouseholdPersonInline.extra == 0


@pytest.mark.django_db
def test_the_person_change_form_renders_no_blank_household_or_committee_row(
    secretariat_client
):
    person = Person.objects.create(last_name="Malong", first_name="Shan Albert")
    response = secretariat_client.get(f"/admin/people/person/{person.pk}/change/")
    body = response.content.decode()
    assert 'name="household_memberships-TOTAL_FORMS" value="0"' in body
    assert 'name="committee_memberships-TOTAL_FORMS" value="0"' in body


@pytest.mark.django_db
def test_the_household_change_form_renders_no_blank_member_row(secretariat_client):
    household = Household.objects.create(name="Malong Family")
    response = secretariat_client.get(f"/admin/people/household/{household.pk}/change/")
    body = response.content.decode()
    # HouseholdMember's related_name from the Household side is "members"
    # (people/models.py), which Django uses as this inline's formset prefix.
    assert 'name="members-TOTAL_FORMS" value="0"' in body


# -- saving unchanged still works -----------------------------------------


@pytest.mark.django_db
def test_saving_a_person_unchanged_still_works_with_no_household(secretariat_client):
    person = Person.objects.create(last_name="Malong", first_name="Shan Albert")
    response = secretariat_client.post(
        f"/admin/people/person/{person.pk}/change/", _person_post_data(person)
    )
    assert response.status_code == 302
    person.refresh_from_db()
    assert person.last_name == "Malong"


@pytest.mark.django_db
def test_saving_a_person_unchanged_still_works_with_an_existing_household(secretariat_client):
    person = Person.objects.create(last_name="Malong", first_name="Shan Albert")
    household = Household.objects.create(name="Malong Family")
    membership = HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )

    post = _person_post_data(person)
    post["household_memberships-TOTAL_FORMS"] = "1"
    post["household_memberships-INITIAL_FORMS"] = "1"
    post["household_memberships-0-id"] = str(membership.pk)
    post["household_memberships-0-household"] = str(household.pk)
    post["household_memberships-0-role"] = membership.role

    response = secretariat_client.post(f"/admin/people/person/{person.pk}/change/", post)
    assert response.status_code == 302
    assert HouseholdMember.objects.filter(pk=membership.pk).exists()


# -- adding a row still works, with extra = 0 ------------------------------


@pytest.mark.django_db
def test_adding_a_household_membership_through_the_admin_still_works(secretariat_client):
    person = Person.objects.create(last_name="Malong", first_name="Shan Albert")
    household = Household.objects.create(name="Malong Family")

    post = _person_post_data(person)
    post["household_memberships-TOTAL_FORMS"] = "1"
    post["household_memberships-0-household"] = str(household.pk)
    post["household_memberships-0-role"] = HouseholdRole.HEAD

    response = secretariat_client.post(f"/admin/people/person/{person.pk}/change/", post)
    assert response.status_code == 302
    assert HouseholdMember.objects.filter(household=household, person=person).exists()


@pytest.mark.django_db
def test_adding_a_committee_membership_through_the_admin_still_works(secretariat_client):
    person = Person.objects.create(last_name="Malong", first_name="Shan Albert")
    committee = Committee.objects.get(code="ict")

    post = _person_post_data(person)
    post["committee_memberships-TOTAL_FORMS"] = "1"
    post["committee_memberships-0-committee"] = str(committee.pk)
    post["committee_memberships-0-role"] = CommitteeRole.MEMBER
    post["committee_memberships-0-date_joined"] = TODAY.isoformat()

    response = secretariat_client.post(f"/admin/people/person/{person.pk}/change/", post)
    assert response.status_code == 302
    assert CommitteeMembership.objects.filter(committee=committee, person=person).exists()
