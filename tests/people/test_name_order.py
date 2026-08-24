"""Surname first in every list of people, with first-name-first as an option.

Requested 2026-08-24. A register is looked up by surname -- it is what the
church's own book of members is ordered by (spec 7.6), it is how the
changelist has always been SORTED, and a column of given names is one you
have to read every row of to find anybody.

The distinction that matters: this is about LISTS. A notice saying "Linked
to existing child Rhyzel Bayatin Abaigar" is a sentence and reads in the
spoken order, so Person.full_name is untouched.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)
from people.naming import GIVEN_FIRST, SESSION_KEY, SURNAME_FIRST

TODAY = timezone.localdate()


def make_user(username="sec", group_name=groups.SECRETARIAT):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.fixture
def rhea(db):
    return Person.objects.create(
        last_name="Santos", first_name="Rhea Marie", middle_name="Bayatin",
        suffix="Jr.", membership_status=MembershipStatus.MEMBER,
    )


# -- the two forms -----------------------------------------------------


def test_sorted_name_files_the_surname_first(rhea):
    assert rhea.sorted_name == "Santos, Rhea Marie Bayatin Jr."


def test_full_name_still_reads_as_it_is_spoken(rhea):
    """Untouched, because it is what goes inside a sentence."""
    assert rhea.full_name == "Rhea Marie Bayatin Santos Jr."


@pytest.mark.django_db
def test_somebody_with_no_surname_is_not_rendered_with_a_stray_comma(db):
    person = Person.objects.create(last_name="", first_name="Mononym")

    assert person.sorted_name == "Mononym"


# -- the standard ------------------------------------------------------


@pytest.mark.django_db
def test_the_people_list_puts_the_surname_first_by_default(client, rhea):
    client.force_login(make_user())

    body = client.get(reverse("admin:people_person_changelist")).content.decode()

    assert "Santos, Rhea Marie" in body


@pytest.mark.django_db
def test_a_household_lists_its_members_surname_first(client, rhea):
    household = Household.objects.create(name="Santos Family")
    HouseholdMember.objects.create(
        household=household, person=rhea, role=HouseholdRole.HEAD
    )
    client.force_login(make_user())

    body = client.get(
        reverse("admin:people_household_view", args=[household.pk])
    ).content.decode()

    assert "Santos, Rhea Marie" in body


@pytest.mark.django_db
def test_a_committee_roster_puts_the_surname_first(client, rhea):
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"), person=rhea,
        role=CommitteeRole.MEMBER, date_joined=TODAY - dt.timedelta(days=30),
    )
    client.force_login(make_user())

    body = client.get(
        reverse(
            "admin:committees_committeemembership_overview_detail",
            args=[Committee.objects.get(code="sunshine").pk],
        )
    ).content.decode()

    assert "Santos, Rhea" in body


# -- the option --------------------------------------------------------


@pytest.mark.django_db
def test_the_order_can_be_switched_and_sticks(client, rhea):
    client.force_login(make_user())

    client.get(reverse("admin:people_person_name_order"))

    assert client.session[SESSION_KEY] == GIVEN_FIRST
    body = client.get(reverse("admin:people_person_changelist")).content.decode()
    assert "Rhea Marie Bayatin Santos" in body
    assert "Santos, Rhea Marie" not in body


@pytest.mark.django_db
def test_switching_twice_returns_to_the_standard(client, rhea):
    client.force_login(make_user())

    client.get(reverse("admin:people_person_name_order"))
    client.get(reverse("admin:people_person_name_order"))

    assert client.session[SESSION_KEY] == SURNAME_FIRST


@pytest.mark.django_db
def test_the_choice_follows_the_user_onto_other_lists(client, rhea):
    """One control, every list -- it is a way of reading, not a setting on
    one screen."""
    household = Household.objects.create(name="Santos Family")
    HouseholdMember.objects.create(
        household=household, person=rhea, role=HouseholdRole.HEAD
    )
    client.force_login(make_user())
    client.get(reverse("admin:people_person_name_order"))

    body = client.get(
        reverse("admin:people_household_view", args=[household.pk])
    ).content.decode()

    assert "Rhea Marie Bayatin Santos" in body


@pytest.mark.django_db
def test_the_switch_returns_the_user_to_the_page_they_were_reading(client, rhea):
    client.force_login(make_user())
    changelist = reverse("admin:people_person_changelist")

    response = client.get(
        reverse("admin:people_person_name_order"), HTTP_REFERER=changelist
    )

    assert response.status_code == 302
    assert response["Location"] == changelist


@pytest.mark.django_db
def test_one_users_choice_does_not_change_anybody_elses(client, rhea):
    from django.test import Client

    client.force_login(make_user("first"))
    client.get(reverse("admin:people_person_name_order"))

    other = Client()
    other.force_login(make_user("second", groups.ICT))
    body = other.get(reverse("admin:people_person_changelist")).content.decode()

    assert "Santos, Rhea Marie" in body


@pytest.mark.django_db
def test_the_people_list_offers_the_switch_and_names_the_other_order(client, rhea):
    """The control names what it will DO, not what is already true -- a
    button labelled with the current state reads as a statement."""
    client.force_login(make_user())

    body = client.get(reverse("admin:people_person_changelist")).content.decode()

    assert "Show First name first" in body
    assert reverse("admin:people_person_name_order") in body


@pytest.mark.django_db
def test_the_switch_then_offers_the_way_back(client, rhea):
    client.force_login(make_user())
    client.get(reverse("admin:people_person_name_order"))

    body = client.get(reverse("admin:people_person_changelist")).content.decode()

    assert "Show Surname first" in body
