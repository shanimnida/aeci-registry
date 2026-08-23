"""Grievance and Reconciliation has no officers of its own.

Recorded 2026-08-24 from the church: "the Grievance and Reconciliation
Committee doesnt need a Chair and Co-Chair, the members are appointed as
well such as the two Pastors of the Church". D7 already made it the one
committee absent from the profiling form; this is the other half of the
same fact -- it is an appointed body, not one led from within.

The consequence is only in reporting: an empty chairperson post is not a
VACANCY here, so the overview must stop calling it one.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import MembershipStatus, Person

GRIEVANCE = "grievance-and-reconciliation"
TODAY = timezone.localdate()


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.fixture
def staffed(db):
    """One member on Grievance and one on Youth.

    The overview shows a card's officer lines only once somebody is on it --
    an empty committee gets "Nobody currently assigned" instead, which would
    make these assertions vacuous.
    """
    for index, code in enumerate((GRIEVANCE, "youth")):
        person = Person.objects.create(
            last_name="Pastor",
            first_name=f"P{index}",
            membership_status=MembershipStatus.MEMBER,
        )
        CommitteeMembership.objects.create(
            committee=Committee.objects.get(code=code),
            person=person,
            role=CommitteeRole.MEMBER,
            date_joined=TODAY - dt.timedelta(days=30),
        )


@pytest.mark.django_db
def test_grievance_is_marked_as_having_no_officers():
    assert Committee.objects.get(code=GRIEVANCE).has_officers is False


@pytest.mark.django_db
def test_every_other_committee_still_has_officers():
    others = Committee.objects.exclude(code=GRIEVANCE)
    assert others.count() == 11
    assert all(committee.has_officers for committee in others)


@pytest.mark.django_db
def test_the_overview_calls_it_an_appointed_body_not_a_vacancy(client, staffed):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(
        reverse("admin:committees_committeemembership_overview")
    ).content.decode()

    assert "Appointed body" in body


@pytest.mark.django_db
def test_the_overview_still_flags_a_real_vacancy_elsewhere(client, staffed):
    """The exemption must be for this committee only -- an unfilled chair on
    Youth is still a gap the Board tracks."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(
        reverse("admin:committees_committeemembership_overview")
    ).content.decode()

    assert "No chairperson assigned" in body


@pytest.mark.django_db
def test_it_is_not_offered_on_the_appointments_screen(client):
    """There are no officer posts to fill. Its members are recorded on the
    ordinary committee-membership screen, which is what they are."""
    client.force_login(make_user("ict", groups.ICT))

    body = client.get(
        reverse("admin:committees_appointment_appoint")
    ).content.decode()

    assert "Grievance and Reconciliation" not in body
    assert "Youth" in body
