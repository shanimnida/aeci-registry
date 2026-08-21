"""BUG (2026-08-22, empty households): build_person_from_import used to
create a Household for every approved row unconditionally, even a single
member with no spouse, no children and no date of marriage -- one person is
not a family. These tests exercise imports.services.build_person_from_import
directly (not through the review admin view -- see tests/imports/test_review.py
and test_family_dedup.py for that) against the new rule: a household is only
created when the row names a spouse, a spouse was matched to an existing
person, at least one child is listed, or a date of marriage is on file.

All names below are fabricated. Real member data lives in `form images/` and
is never used in fixtures or tests.
"""

import datetime as dt

import pytest

from imports.services import build_person_from_import
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person


@pytest.mark.django_db
def test_single_member_with_no_spouse_or_children_creates_no_household(ict_user):
    cleaned = {
        "last_name": "Reyes",
        "first_name": "Carlos",
        "home_address": "123 Fictional St, Baguio City",
        "membership_status": MembershipStatus.MEMBER,
    }

    person, notices = build_person_from_import(cleaned, [], ict_user)

    assert Person.objects.count() == 1
    assert Household.objects.count() == 0
    assert HouseholdMember.objects.count() == 0
    # Nothing lost: the address this person gave lives on their own record.
    assert person.home_address == "123 Fictional St, Baguio City"
    assert notices == []


@pytest.mark.django_db
def test_member_with_children_gets_a_household_containing_them(ict_user):
    cleaned = {
        "last_name": "Santos",
        "first_name": "Bea",
        "home_address": "45 Fictional Ave, Baguio City",
        "membership_status": MembershipStatus.MEMBER,
    }
    children = [{"full_name": "Miguel Santos", "date_of_birth": "2015-01-01"}]

    person, notices = build_person_from_import(cleaned, children, ict_user)

    assert Household.objects.count() == 1
    household = Household.objects.get()
    assert household.members.count() == 2
    roles = list(household.members.values_list("role", flat=True))
    assert roles.count(HouseholdRole.HEAD) == 1
    assert roles.count(HouseholdRole.CHILD) == 1
    child = Person.objects.get(membership_status=MembershipStatus.CHILD)
    assert HouseholdMember.objects.filter(household=household, person=person).exists()
    assert HouseholdMember.objects.filter(household=household, person=child).exists()


@pytest.mark.django_db
def test_member_with_a_spouse_name_but_no_children_gets_a_household(ict_user):
    cleaned = {
        "last_name": "Cruz",
        "first_name": "Danilo",
        "spouse_name": "Marites Cruz",  # never submitted her own form
        "membership_status": MembershipStatus.MEMBER,
    }

    person, notices = build_person_from_import(cleaned, [], ict_user)

    assert Household.objects.count() == 1
    household = Household.objects.get()
    assert household.members.count() == 1
    member = household.members.get()
    assert member.role == HouseholdRole.HEAD
    assert member.person == person
    # No existing Marites Cruz to match, so no spouse-linked notice.
    assert notices == []


@pytest.mark.django_db
def test_member_with_only_a_date_of_marriage_gets_a_household_and_the_date_is_preserved(ict_user):
    """Household.date_of_marriage has no home on Person -- a married member
    whose spouse never submitted their own form (so spouse_name might be
    blank too) must not have this date silently discarded."""
    cleaned = {
        "last_name": "Domingo",
        "first_name": "Eliza",
        "date_of_marriage": "2010-05-01",
        "membership_status": MembershipStatus.MEMBER,
    }

    person, notices = build_person_from_import(cleaned, [], ict_user)

    assert Household.objects.count() == 1
    household = Household.objects.get()
    assert household.date_of_marriage == dt.date(2010, 5, 1)
    assert household.members.count() == 1
    assert household.members.get().role == HouseholdRole.HEAD


@pytest.mark.django_db
def test_an_ambiguous_spouse_match_still_gets_a_household_since_the_form_names_a_spouse(ict_user):
    """The form naming a spouse is enough on its own (the rule does not
    require the match to succeed) -- an ambiguous match must not silently
    fall back to 'no household' just because nothing could be linked."""
    Person.objects.create(last_name="Reyes", first_name="Jomar")
    Person.objects.create(last_name="Reyes", first_name="Jomar")  # two candidates -> ambiguous

    cleaned = {
        "last_name": "Reyes",
        "first_name": "Liza",
        "spouse_name": "Jomar Reyes",
        "membership_status": MembershipStatus.MEMBER,
    }

    person, notices = build_person_from_import(cleaned, [], ict_user)

    assert Household.objects.count() == 1
    household = Household.objects.get()
    assert household.members.count() == 1  # not linked -- ambiguous
    assert any("matches more than one existing person" in notice for notice in notices)


@pytest.mark.django_db
def test_a_reused_household_with_no_marriage_date_takes_this_rows(ict_user):
    """Both halves of a married couple fill in their own form and only one
    may have written the wedding date down. date_of_marriage has no home on
    Person, so reusing the spouse's existing household used to drop it."""
    build_person_from_import(
        {"last_name": "Lim", "first_name": "Grace", "spouse_name": "Peter Lim",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Anna Lim", "date_of_birth": "2016-03-03"}],
        ict_user,
    )
    household = Household.objects.get()
    assert household.date_of_marriage is None

    _, notices = build_person_from_import(
        {"last_name": "Lim", "first_name": "Peter", "spouse_name": "Grace Lim",
         "date_of_marriage": "2012-04-04", "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )

    assert Household.objects.count() == 1  # reused, not a second one
    household.refresh_from_db()
    assert household.date_of_marriage == dt.date(2012, 4, 4)
    assert any("date of marriage (2012-04-04)" in notice for notice in notices)


@pytest.mark.django_db
def test_a_reused_household_keeps_its_own_marriage_date_and_reports_the_conflict(ict_user):
    """Two paper forms disagreeing about a wedding date is a question for
    the reviewer holding both sheets, not something to settle by approval
    order. The stored date stands and the reviewer is told."""
    build_person_from_import(
        {"last_name": "Yap", "first_name": "Rina", "spouse_name": "Alvin Yap",
         "date_of_marriage": "2008-09-09", "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )
    household = Household.objects.get()
    assert household.date_of_marriage == dt.date(2008, 9, 9)

    _, notices = build_person_from_import(
        {"last_name": "Yap", "first_name": "Alvin", "spouse_name": "Rina Yap",
         "date_of_marriage": "2008-09-10", "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )

    household.refresh_from_db()
    assert household.date_of_marriage == dt.date(2008, 9, 9)  # not overwritten
    assert any("already records 2008-09-09" in notice for notice in notices)


@pytest.mark.django_db
def test_a_matching_marriage_date_on_a_reused_household_reports_nothing(ict_user):
    """The review form hands dates over as free text, so the stored date is
    a date object and this row's is a string -- comparing them raw would
    report a disagreement that is not there."""
    build_person_from_import(
        {"last_name": "Ocampo", "first_name": "Nena", "spouse_name": "Ruben Ocampo",
         "date_of_marriage": "2005-07-07", "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )

    _, notices = build_person_from_import(
        {"last_name": "Ocampo", "first_name": "Ruben", "spouse_name": "Nena Ocampo",
         "date_of_marriage": "2005-07-07", "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )

    assert Household.objects.get().date_of_marriage == dt.date(2005, 7, 7)
    assert not any("date of marriage" in notice for notice in notices)
