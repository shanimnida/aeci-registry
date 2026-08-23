"""BUG (2026-08-23, middle names): a child written on one parent's form with
a middle name and on the other's without one became two Person rows, and did
it silently -- not even flagged as an ambiguous match for the reviewer to
resolve.

Two separate faults, both here:

1. `_split_child_name` folded the middle name into `first_name`, so
   "Rhyzel Bayatin Abaigar" was stored as first_name="Rhyzel Bayatin",
   middle_name="". The middle name was not merely unmatched, it was in the
   wrong field.
2. `_find_child_match` compared `first_name` exactly, so "Rhyzel Bayatin"
   never matched a properly encoded "Rhyzel" + "Bayatin", and -- because no
   candidate existed at all -- it returned "no match" rather than
   "ambiguous", creating a second child with no warning.

All names below are fabricated except the shape of the reported case. Real
member data lives in `form images/` and is never used in fixtures or tests.
"""

import datetime as dt

import pytest

from imports.services import _find_child_match, _split_child_name, build_person_from_import
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person

DOB = dt.date(2015, 4, 4)


# -- splitting ----------------------------------------------------------


@pytest.mark.parametrize(
    "full_name,parent_last,expected",
    [
        ("Rhyzel Bayatin Abaigar", "Abaigar", ("Rhyzel", "Bayatin", "Abaigar")),
        ("Rhyzel Abaigar", "Abaigar", ("Rhyzel", "", "Abaigar")),
        # Two given names plus a middle name: the LAST remaining token is the
        # middle name, which is the Filipino convention the paper form follows.
        ("Juan Miguel Reyes Delacruz", "Delacruz", ("Juan Miguel", "Reyes", "Delacruz")),
        # Surname not the parent's (a child under a different surname).
        ("Maria Santos", "Delacruz", ("Maria", "", "Santos")),
        ("Maria Cruz Santos", "Delacruz", ("Maria", "Cruz", "Santos")),
        # A single word is all AEGIS has; it becomes the first name.
        ("Rhyzel", "Abaigar", ("Rhyzel", "", "Abaigar")),
    ],
)
def test_a_child_name_splits_into_first_middle_and_last(full_name, parent_last, expected):
    assert _split_child_name(full_name, parent_last) == expected


# -- matching -----------------------------------------------------------


@pytest.fixture
def encoded_child(db):
    """Rhyzel as the Secretariat would encode her by hand: middle name in
    its own field."""
    return Person.objects.create(
        first_name="Rhyzel",
        middle_name="Bayatin",
        last_name="Abaigar",
        date_of_birth=DOB,
        membership_status=MembershipStatus.CHILD,
    )


@pytest.mark.django_db
def test_a_name_carrying_the_middle_name_matches_a_record_that_splits_it(encoded_child):
    """The reported case. 'Rhyzel Bayatin Abaigar' on the form must find the
    existing Rhyzel + Bayatin + Abaigar."""
    match, ambiguous = _find_child_match("Rhyzel", "Bayatin", "Abaigar", DOB)

    assert match == encoded_child
    assert not ambiguous


@pytest.mark.django_db
def test_a_name_missing_the_middle_name_still_matches(encoded_child):
    """The other half of the same case: one parent's form omits it."""
    match, ambiguous = _find_child_match("Rhyzel", "", "Abaigar", DOB)

    assert match == encoded_child
    assert not ambiguous


@pytest.mark.django_db
def test_a_legacy_row_with_the_middle_name_glued_into_the_first_name_still_matches():
    """Rows the bug already wrote have first_name='Rhyzel Bayatin' and a
    blank middle_name. Those must match too, or the fix would leave the
    records it exists to reconcile permanently unmatchable."""
    legacy = Person.objects.create(
        first_name="Rhyzel Bayatin",
        last_name="Abaigar",
        date_of_birth=DOB,
        membership_status=MembershipStatus.CHILD,
    )

    assert _find_child_match("Rhyzel", "Bayatin", "Abaigar", DOB) == (legacy, False)
    assert _find_child_match("Rhyzel", "", "Abaigar", DOB) == (legacy, False)


@pytest.mark.django_db
def test_a_different_middle_name_is_not_the_same_child(encoded_child):
    """Tolerating a MISSING middle name is not the same as tolerating a
    CONTRADICTORY one. Two children of one family can share a first name and
    a birthday only by coincidence, but a different middle name is positive
    evidence of a different person -- so this refuses rather than links."""
    match, ambiguous = _find_child_match("Rhyzel", "Domingo", "Abaigar", DOB)

    assert match is None
    assert ambiguous


@pytest.mark.django_db
def test_a_different_first_name_is_never_a_match(encoded_child):
    match, ambiguous = _find_child_match("Rhonalyn", "Bayatin", "Abaigar", DOB)

    assert match is None
    assert not ambiguous


@pytest.mark.django_db
def test_two_candidates_sharing_a_birthday_are_still_ambiguous(encoded_child):
    """R30 stands: where AEGIS cannot narrow to exactly one, it refuses and
    asks the reviewer rather than guessing."""
    Person.objects.create(
        first_name="Rhyzel",
        middle_name="Bayatin",
        last_name="Abaigar",
        date_of_birth=DOB,
        membership_status=MembershipStatus.CHILD,
    )

    match, ambiguous = _find_child_match("Rhyzel", "Bayatin", "Abaigar", DOB)

    assert match is None
    assert ambiguous


@pytest.mark.django_db
def test_a_child_with_no_birthdate_on_the_form_is_ambiguous_not_a_silent_new_person(encoded_child):
    match, ambiguous = _find_child_match("Rhyzel", "Bayatin", "Abaigar", None)

    assert match is None
    assert ambiguous


@pytest.mark.django_db
def test_a_household_narrows_two_same_birthday_candidates_to_the_family_one():
    """The signal the old matcher never used: the child is being recorded
    from a parent's form, so a candidate already in that family's household
    is the one meant -- while a same-named, same-aged stranger is not."""
    household = Household.objects.create(name="Abaigar Family")
    ours = Person.objects.create(
        first_name="Rhyzel", middle_name="Bayatin", last_name="Abaigar",
        date_of_birth=DOB, membership_status=MembershipStatus.CHILD,
    )
    HouseholdMember.objects.create(
        household=household, person=ours, role=HouseholdRole.CHILD
    )
    Person.objects.create(  # unrelated, same name and birthday
        first_name="Rhyzel", middle_name="Bayatin", last_name="Abaigar",
        date_of_birth=DOB, membership_status=MembershipStatus.CHILD,
    )

    match, ambiguous = _find_child_match(
        "Rhyzel", "Bayatin", "Abaigar", DOB, household=household
    )

    assert match == ours
    assert not ambiguous


# -- end to end ---------------------------------------------------------


@pytest.mark.django_db
def test_both_parents_forms_produce_one_child_however_the_name_was_written(ict_user):
    """The whole bug, through the real approval path: the father's form
    writes the middle name, the mother's does not."""
    build_person_from_import(
        {"last_name": "Abaigar", "first_name": "Dado",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Rhyzel Bayatin Abaigar", "date_of_birth": "2015-04-04"}],
        ict_user,
    )
    _, notices = build_person_from_import(
        {"last_name": "Abaigar", "first_name": "Marisol", "spouse_name": "Dado Abaigar",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Rhyzel Abaigar", "date_of_birth": "2015-04-04"}],
        ict_user,
    )

    children = Person.objects.filter(membership_status=MembershipStatus.CHILD)
    assert children.count() == 1
    child = children.get()
    assert (child.first_name, child.middle_name, child.last_name) == (
        "Rhyzel", "Bayatin", "Abaigar",
    )
    assert any("Linked to existing child" in notice for notice in notices)


@pytest.mark.django_db
def test_the_middle_name_lands_in_its_own_field_not_glued_to_the_first(ict_user):
    build_person_from_import(
        {"last_name": "Abaigar", "first_name": "Dado",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Rhyzel Bayatin Abaigar", "date_of_birth": "2015-04-04"}],
        ict_user,
    )

    child = Person.objects.get(membership_status=MembershipStatus.CHILD)
    assert child.first_name == "Rhyzel"
    assert child.middle_name == "Bayatin"


@pytest.mark.django_db
def test_a_form_naming_the_middle_name_fills_a_blank_one_on_the_existing_record(ict_user):
    """The first form to arrive omitted the middle name; the second supplies
    it. Linking must not throw that away -- it is the fuller record."""
    build_person_from_import(
        {"last_name": "Abaigar", "first_name": "Dado",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Rhyzel Abaigar", "date_of_birth": "2015-04-04"}],
        ict_user,
    )
    assert Person.objects.get(membership_status=MembershipStatus.CHILD).middle_name == ""

    _, notices = build_person_from_import(
        {"last_name": "Abaigar", "first_name": "Marisol", "spouse_name": "Dado Abaigar",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Rhyzel Bayatin Abaigar", "date_of_birth": "2015-04-04"}],
        ict_user,
    )

    child = Person.objects.get(membership_status=MembershipStatus.CHILD)
    assert child.middle_name == "Bayatin"
    assert any("middle name" in notice.lower() for notice in notices)
