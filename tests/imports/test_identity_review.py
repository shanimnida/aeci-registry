"""A possible identity match is evidence for the reviewer, never a verdict."""

from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group, User

from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person
from tests.imports.test_review import _base_post_data, _review_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer():
    user = User.objects.create_user("identity_reviewer", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def stage():
    def make(**changes):
        data = {
            "first_name": "Marlon", "last_name": "Synthetic",
            "date_of_birth": "1980-01-01", "form_version": "v3",
            "certification_date": "2020-01-01", "committees": [],
            "children": [{"full_name": "John Marlon E. Synthetic", "date_of_birth": "2010-01-01"}],
            "_registration": {"consent_version": "v3-web-2026-11", "consent_given": True},
        }
        data.update(changes)
        batch = ImportBatch.objects.create(
            source_filename="Website registration", website_submission_id=uuid4(),
        )
        return StagedPerson.objects.create(batch=batch, sequence=0, raw_data=data)
    return make


def existing_child(*, dob=date(2009, 1, 1), middle="E.", household=True):
    guardian = Person.objects.create(first_name="Existing", last_name="Parent", date_of_birth="1970-01-01")
    child = Person.objects.create(
        first_name="John Marlon", middle_name=middle, last_name="Synthetic",
        date_of_birth=dob, guardian=guardian, membership_status=MembershipStatus.CHILD,
    )
    family = None
    if household:
        family = Household.objects.create(name="Existing household")
        HouseholdMember.objects.create(household=family, person=guardian, role=HouseholdRole.HEAD)
        HouseholdMember.objects.create(household=family, person=child, role=HouseholdRole.CHILD)
    return child, guardian, family


def approve(client, reviewer, row, **choices):
    client.force_login(reviewer)
    post = _base_post_data(row)
    post.update(choices)
    return client.post(_review_url(row.batch, row), post)


def test_a_different_child_can_be_approved_without_changing_or_joining_the_namesakes_family(client, reviewer, stage):
    child, guardian, family = existing_child()
    row = stage()
    original_submission = deepcopy(row.raw_data)

    response = approve(client, reviewer, row, **{"children-0-person_resolution": "new"})

    assert response.status_code == 302
    row.refresh_from_db()
    child.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    assert row.reviewed_by == reviewer and row.reviewed_at is not None
    assert row.edited_data["children"][0]["person_resolution"] == "new"
    assert "Different person" in row.edited_data["_identity_decisions"][0]
    assert row.raw_data == original_submission
    assert child.date_of_birth == date(2009, 1, 1) and child.guardian == guardian
    separate = Person.objects.get(guardian=row.created_person)
    assert separate.pk != child.pk and separate.date_of_birth == date(2010, 1, 1)
    assert Household.objects.count() == 2
    assert set(family.members.values_list("person_id", flat=True)) == {child.pk, guardian.pk}
    assert not family.members.filter(person=row.created_person).exists()
    decided_page = client.get(_review_url(row.batch, row))
    assert decided_page.status_code == 200
    assert "Reviewer's identity decisions" in decided_page.content.decode()


def test_a_reviewer_can_link_a_child_with_missing_birthdate_without_overwriting_the_existing_identity(client, reviewer, stage):
    child, guardian, family = existing_child(dob=None, middle="")
    row = stage()
    response = approve(client, reviewer, row, **{"children-0-person_resolution": f"link:{child.pk}"})

    assert response.status_code == 302
    row.refresh_from_db()
    child.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    assert Person.objects.count() == 3 and Household.objects.count() == 1
    assert child.date_of_birth is None and child.middle_name == ""
    assert child.guardian == guardian
    assert family.members.filter(person=row.created_person).exists()
    assert row.edited_data["children"][0]["person_resolution"] == f"link:{child.pk}"


@pytest.mark.parametrize("candidate_count", [1, 2])
def test_even_a_single_exact_child_match_requires_the_reviewers_choice(client, reviewer, stage, candidate_count):
    child, _, _ = existing_child(dob=date(2010, 1, 1))
    if candidate_count == 2:
        Person.objects.create(
            first_name=child.first_name, middle_name=child.middle_name,
            last_name=child.last_name, date_of_birth=child.date_of_birth,
            membership_status=MembershipStatus.CHILD,
        )
    row = stage()
    client.force_login(reviewer)
    page = client.get(_review_url(row.batch, row))
    field = page.context["formset"].forms[0].fields["person_resolution"]
    assert field.choices[0][0] == ""
    assert page.context["formset"].forms[0]["person_resolution"].value() in (None, "")
    before = (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count())

    response = client.post(_review_url(row.batch, row), _base_post_data(row))

    assert response.status_code == 200
    assert "person_resolution" in response.context["formset"].forms[0].errors
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING and row.created_person_id is None
    assert (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count()) == before


@pytest.mark.parametrize("stale", [False, True], ids=["unrelated-id", "deleted-sole-candidate"])
def test_an_unrelated_or_stale_candidate_id_cannot_turn_into_an_approval(client, reviewer, stage, stale):
    child, _, _ = existing_child()
    row = stage()
    client.force_login(reviewer)
    assert client.get(_review_url(row.batch, row)).status_code == 200
    if stale:
        choice = f"link:{child.pk}"
        child.delete()
    else:
        stranger = Person.objects.create(first_name="Unrelated", last_name="Stranger")
        choice = f"link:{stranger.pk}"
    before = (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count())

    response = approve(client, reviewer, row, **{"children-0-person_resolution": choice})

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING and row.created_person_id is None
    assert (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count()) == before


def test_a_candidate_that_changes_after_form_validation_rolls_back_the_whole_approval(client, reviewer, stage, monkeypatch):
    child, _, _ = existing_child()
    row = stage()
    before = (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count())
    # The form still has the actual candidate. The service's later lookup
    # represents that identity becoming unavailable while the POST runs.
    monkeypatch.setattr("imports.services.child_candidates", lambda *args: [])

    response = approve(client, reviewer, row, **{"children-0-person_resolution": f"link:{child.pk}"})

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING and row.created_person_id is None
    assert row.error_message
    assert (Person.objects.count(), Household.objects.count(), HouseholdMember.objects.count()) == before


@pytest.mark.parametrize("role", [groups.CHAIRPERSON, groups.BOARD])
def test_identity_choices_do_not_give_other_roles_approval_permission(client, stage, role):
    child, _, _ = existing_child()
    row = stage()
    user = User.objects.create_user("other_role", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    before = Person.objects.count()

    response = approve(client, user, row, **{"children-0-person_resolution": "new"})

    assert response.status_code == 403
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING and row.created_person_id is None
    assert Person.objects.count() == before
    assert Person.objects.filter(pk=child.pk).exists()


@pytest.mark.parametrize("link", [False, True], ids=["separate-person", "their-own-record"])
def test_the_reviewer_decides_whether_an_earlier_child_record_is_the_form_subject(client, reviewer, stage, link):
    earlier = Person.objects.create(
        first_name="Rhyzel", last_name="Synthetic", date_of_birth="2000-03-03",
        membership_status=MembershipStatus.CHILD,
    )
    row = stage(first_name="Rhyzel", middle_name="Bayatin", date_of_birth="2000-03-03", children=[])
    original_submission = deepcopy(row.raw_data)
    choice = f"link:{earlier.pk}" if link else "new"

    response = approve(client, reviewer, row, person_resolution=choice)

    assert response.status_code == 302
    row.refresh_from_db()
    earlier.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    assert (row.created_person_id == earlier.pk) is link
    assert Person.objects.count() == (1 if link else 2)
    assert earlier.membership_status == MembershipStatus.CHILD
    assert earlier.middle_name == ("Bayatin" if link else "")
    assert row.edited_data["person_resolution"] == choice
    assert row.raw_data == original_submission


def test_an_earlier_child_record_is_never_updated_without_an_explicit_choice(client, reviewer, stage):
    earlier = Person.objects.create(first_name="Rhyzel", last_name="Synthetic", membership_status=MembershipStatus.CHILD)
    row = stage(first_name="Rhyzel", middle_name="Bayatin", children=[])

    response = approve(client, reviewer, row)

    assert response.status_code == 200
    assert "person_resolution" in response.context["form"].errors
    row.refresh_from_db()
    earlier.refresh_from_db()
    assert row.status == StagedPersonStatus.PENDING
    assert Person.objects.count() == 1 and earlier.middle_name == ""


@pytest.mark.parametrize("choice", [None, "new", "link"], ids=["no-auto-link", "separate-spouse", "confirmed-spouse"])
def test_even_a_unique_spouse_match_is_the_reviewers_decision(client, reviewer, stage, choice):
    spouse = Person.objects.create(first_name="Alex", last_name="Reyes", date_of_birth="1980-01-01")
    family = Household.objects.create(name="Alex existing family")
    HouseholdMember.objects.create(household=family, person=spouse, role=HouseholdRole.HEAD)
    row = stage(children=[], spouse_name="Alex Reyes")
    choices = {} if choice is None else {"spouse_resolution": f"link:{spouse.pk}" if choice == "link" else choice}

    response = approve(client, reviewer, row, **choices)

    row.refresh_from_db()
    if choice is None:
        assert response.status_code == 200
        assert "spouse_resolution" in response.context["form"].errors
        assert row.status == StagedPersonStatus.PENDING
        assert Person.objects.count() == 1 and Household.objects.count() == 1
    else:
        assert response.status_code == 302 and row.status == StagedPersonStatus.APPROVED
        assert Person.objects.count() == 2
        assert family.members.filter(person=row.created_person).exists() is (choice == "link")
        assert Household.objects.count() == (1 if choice == "link" else 2)
        assert row.edited_data["spouse_resolution"] == choices["spouse_resolution"]
