"""An ex-officio member says which office put them there.

Asked for 2026-08-24: the Secretariat roster lists everybody who is a
secretary of another committee, and a bare name does not say why they are
on it. "Rhem Mc Garth Santos — ICT Secretary" does, and it is the fact that
sends somebody to the right person.

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
from people.models import MembershipStatus, Person

TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=30)


def make_secretary(first_name, committee_code):
    person = Person.objects.create(
        last_name="Santos", first_name=first_name,
        membership_status=MembershipStatus.MEMBER,
    )
    # save() seats them on Secretariat automatically.
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code=committee_code),
        person=person,
        role=CommitteeRole.SECRETARY,
        date_joined=JOINED,
    )
    return person


def secretariat_detail_url():
    return reverse(
        "admin:committees_committeemembership_overview_detail",
        args=[Committee.objects.get(code="secretariat").pk],
    )


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.mark.django_db
def test_the_secretariat_roster_names_the_committee_they_are_secretary_of(client):
    make_secretary("Rhem", "ict")
    make_secretary("Hazel", "youth")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(secretariat_detail_url()).content.decode()

    assert "ICT Secretary" in body
    assert "Youth Secretary" in body


@pytest.mark.django_db
def test_somebody_holding_two_secretary_posts_has_both_named(client):
    person = make_secretary("Rhem", "ict")
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="food"),
        person=person,
        role=CommitteeRole.SECRETARY,
        date_joined=JOINED,
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(secretariat_detail_url()).content.decode()

    assert "Food Secretary" in body
    assert "ICT Secretary" in body


@pytest.mark.django_db
def test_an_ordinary_member_reads_as_an_ordinary_member(client):
    """The label is for people who are there ex officio. Somebody who
    volunteered for the Secretariat did not arrive by way of an office."""
    volunteer = Person.objects.create(
        last_name="Santos", first_name="Ordinary",
        membership_status=MembershipStatus.MEMBER,
    )
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="secretariat"),
        person=volunteer,
        role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(secretariat_detail_url()).content.decode()

    assert "Ordinary" in body
    assert "Secretary" not in body.split("Ordinary")[1][:200]


@pytest.mark.django_db
def test_ending_the_secretary_post_removes_them_from_the_roster(client):
    """The seat follows the office. When the office ends so does the seat,
    and there is nothing left to label."""
    person = make_secretary("Rhem", "ict")
    post = CommitteeMembership.objects.get(
        person=person, committee__code="ict", role=CommitteeRole.SECRETARY
    )
    post.date_left = TODAY - dt.timedelta(days=1)
    post.save()
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(secretariat_detail_url()).content.decode()

    assert "ICT Secretary" not in body
