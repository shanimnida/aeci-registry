import datetime as dt

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.test import RequestFactory
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.admin import CHAIRPERSON_FIELDS, PersonAdmin
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
    CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=ict, person=on_my_committee, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, on_my_committee, stranger


def request_for(user):
    request = RequestFactory().get("/admin/people/person/")
    request.user = user
    return request


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committee(chair_setup):
    user, mine, stranger = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    visible = admin.get_queryset(request_for(user))
    assert mine in visible
    assert stranger not in visible


@pytest.mark.django_db
def test_a_chairperson_sees_only_five_fields(chair_setup):
    user, _, _ = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    assert tuple(admin.get_fields(request_for(user))) == CHAIRPERSON_FIELDS


@pytest.mark.django_db
def test_a_chairperson_never_sees_an_address_or_birthdate(chair_setup):
    user, _, _ = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    fields = set(admin.get_fields(request_for(user)))
    for hidden in ("home_address", "date_of_birth", "civil_status", "notes"):
        assert hidden not in fields


@pytest.mark.django_db
def test_the_secretariat_sees_everyone(db):
    Person.objects.create(last_name="Santos", first_name="Rhea")
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    admin = PersonAdmin(Person, AdminSite())
    assert admin.get_queryset(request_for(user)).count() == 1
