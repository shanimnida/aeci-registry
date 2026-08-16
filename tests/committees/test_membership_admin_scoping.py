import datetime as dt

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.test import RequestFactory
from django.utils import timezone

from committees.admin import CommitteeMembershipAdmin
from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import Person

TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=7)


@pytest.fixture
def chair_setup(db):
    chair_person = Person.objects.create(last_name="Malong", first_name="Shan")
    on_my_committee = Person.objects.create(last_name="Reyes", first_name="Manex")
    stranger = Person.objects.create(last_name="Santos", first_name="Rhea")

    ict = Committee.objects.get(code="ict")
    food = Committee.objects.get(code="food")
    mine = CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
    )
    on_my_committee_membership = CommitteeMembership.objects.create(
        committee=ict, person=on_my_committee, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    stranger_membership = CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, on_my_committee_membership, stranger_membership


def request_for(user):
    request = RequestFactory().get("/admin/committees/committeemembership/")
    request.user = user
    return request


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committees_memberships(chair_setup):
    user, mine, stranger = chair_setup
    admin = CommitteeMembershipAdmin(CommitteeMembership, AdminSite())
    visible = admin.get_queryset(request_for(user))
    assert mine in visible
    assert stranger not in visible


@pytest.mark.django_db
def test_a_chairperson_cannot_read_committee_membership_history(client, chair_setup):
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/committees/committeemembership/{mine.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_read_a_strangers_committee_membership_history(client, chair_setup):
    user, _, stranger = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/committees/committeemembership/{stranger.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_the_board_sees_every_membership(db):
    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    food = Committee.objects.get(code="food")
    CommitteeMembership.objects.create(
        committee=food, person=person, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )
    user = User.objects.create_user("board", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.BOARD))
    admin = CommitteeMembershipAdmin(CommitteeMembership, AdminSite())
    assert admin.get_queryset(request_for(user)).count() == 1
