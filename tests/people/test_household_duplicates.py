"""Merging households that are one family entered twice.

Added 2026-08-24, because fixing the importer does nothing about the pairs
it already wrote. The church asked directly: "how do i merge the reyes
family then".

Merging households is simpler than merging people. A household is a name,
an address, a wedding date, and its members -- so the merge moves the
members and fills gaps, and there is no question of whose birthdate is
right.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from people.duplicates import find_duplicate_household_pairs, merge_households
from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)


def duplicates_url():
    return reverse("admin:people_person_duplicates")


def ict_user():
    user = User.objects.create_user("ict", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.ICT))
    return user


def person(first_name, last_name="Reyes"):
    return Person.objects.create(
        last_name=last_name,
        first_name=first_name,
        membership_status=MembershipStatus.MEMBER,
    )


@pytest.fixture
def split_reyes_family(db):
    """What the bug produced: two households, the child in both."""
    child = Person.objects.create(
        last_name="Reyes", first_name="Ana",
        membership_status=MembershipStatus.CHILD,
        date_of_birth=dt.date(2014, 1, 1),
    )
    first = Household.objects.create(
        name="Reyes Family", address="9 Fictional Street, La Trinidad"
    )
    HouseholdMember.objects.create(
        household=first, person=person("Juan"), role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=first, person=child, role=HouseholdRole.CHILD
    )

    second = Household.objects.create(name="Reyes Family")
    HouseholdMember.objects.create(
        household=second, person=person("Maria"), role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=second, person=child, role=HouseholdRole.CHILD
    )
    return first, second


# -- finding -----------------------------------------------------------


@pytest.mark.django_db
def test_two_households_sharing_a_member_are_found(split_reyes_family):
    """Somebody recorded in both is not a coincidence -- it is exactly what
    the duplicate-household bug produced."""
    pairs = find_duplicate_household_pairs()

    assert len(pairs) == 1
    assert "recorded in both" in pairs[0].reason


@pytest.mark.django_db
def test_two_households_with_the_same_name_and_address_are_found(db):
    same = "9 Fictional Street, La Trinidad"
    Household.objects.create(name="Reyes Family", address=same)
    Household.objects.create(name="Reyes Family", address=same)

    pairs = find_duplicate_household_pairs()

    assert len(pairs) == 1
    assert "weaker evidence" in pairs[0].reason


@pytest.mark.django_db
def test_the_same_name_alone_is_not_evidence(db):
    """"Reyes Family" is a common name here. Flagging every pair of them
    would bury the real ones."""
    Household.objects.create(name="Reyes Family", address="9 Fictional Street")
    Household.objects.create(name="Reyes Family", address="41 Another Road")

    assert find_duplicate_household_pairs() == []


@pytest.mark.django_db
def test_two_ordinary_households_are_not_a_pair(db):
    Household.objects.create(name="Reyes Family", address="9 Fictional Street")
    Household.objects.create(name="Balicao Family", address="41 Another Road")

    assert find_duplicate_household_pairs() == []


# -- merging -----------------------------------------------------------


@pytest.mark.django_db
def test_merging_moves_the_members_across_and_deletes_the_other(split_reyes_family):
    first, second = split_reyes_family

    moved = merge_households(keep=first, remove=second)

    assert not Household.objects.filter(pk=second.pk).exists()
    assert first.members.count() == 3  # Juan, Ana, Maria
    assert moved["members"] == 1  # only Maria; Ana was already there


@pytest.mark.django_db
def test_a_member_already_in_the_kept_household_is_not_duplicated(split_reyes_family):
    first, second = split_reyes_family

    moved = merge_households(keep=first, remove=second)

    ana = Person.objects.get(first_name="Ana")
    assert ana.household_memberships.count() == 1
    assert moved["dropped"] == 1


@pytest.mark.django_db
def test_a_gap_on_the_kept_household_is_filled_from_the_other(db):
    keep = Household.objects.create(name="Reyes Family")
    remove = Household.objects.create(
        name="Reyes Family",
        address="9 Fictional Street",
        date_of_marriage=dt.date(2011, 5, 5),
    )
    HouseholdMember.objects.create(
        household=remove, person=person("Maria"), role=HouseholdRole.HEAD
    )

    moved = merge_households(keep=keep, remove=remove)

    keep.refresh_from_db()
    assert keep.address == "9 Fictional Street"
    assert keep.date_of_marriage == dt.date(2011, 5, 5)
    assert set(moved["filled"]) == {"address", "date of marriage"}


@pytest.mark.django_db
def test_the_kept_households_own_answers_are_never_overruled(db):
    """Somebody already recorded an answer there, and a merge is not the
    place to overrule it."""
    keep = Household.objects.create(
        name="Reyes Family",
        address="Kept address",
        date_of_marriage=dt.date(2011, 5, 5),
    )
    remove = Household.objects.create(
        name="Reyes Family",
        address="Other address",
        date_of_marriage=dt.date(1999, 1, 1),
    )

    merge_households(keep=keep, remove=remove)

    keep.refresh_from_db()
    assert keep.address == "Kept address"
    assert keep.date_of_marriage == dt.date(2011, 5, 5)


@pytest.mark.django_db
def test_nobody_is_deleted_by_a_household_merge(split_reyes_family):
    """Households merge; people do not. Everyone in both survives."""
    first, second = split_reyes_family
    before = set(Person.objects.values_list("pk", flat=True))

    merge_households(keep=first, remove=second)

    assert set(Person.objects.values_list("pk", flat=True)) == before


# -- the screen --------------------------------------------------------


@pytest.mark.django_db
def test_the_duplicates_screen_shows_the_household_pair(client, split_reyes_family):
    client.force_login(ict_user())

    body = client.get(duplicates_url()).content.decode()

    assert "Households" in body
    assert "recorded in both" in body


@pytest.mark.django_db
def test_posting_a_household_choice_merges_and_reports_it(client, split_reyes_family):
    first, second = split_reyes_family
    client.force_login(ict_user())

    response = client.post(
        duplicates_url(),
        {"kind": "household", "keep": first.pk, "remove": second.pk},
        follow=True,
    )

    assert not Household.objects.filter(pk=second.pk).exists()
    assert "Merged" in response.content.decode()


@pytest.mark.django_db
def test_a_nonsense_household_post_changes_nothing(client, split_reyes_family):
    first, second = split_reyes_family
    client.force_login(ict_user())

    client.post(
        duplicates_url(), {"kind": "household", "keep": first.pk, "remove": first.pk}
    )

    assert Household.objects.count() == 2


@pytest.mark.django_db
def test_a_clean_register_says_so(client, db):
    client.force_login(ict_user())

    body = client.get(duplicates_url()).content.decode()

    assert "no two people and no two households" in body
