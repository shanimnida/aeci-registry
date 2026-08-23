"""Children are editable on their parent's own record.

Asked for 2026-08-24: "the children section got removed on editing a
person, i shuld be able to edit this". It had never been there -- the
household inline shows which household somebody is IN, which is a
different question -- but `Person.guardian` is the relationship the
importer fills for every child it creates from a parent's form, so the
children were already recorded with nowhere to edit them.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import MembershipStatus, Person


def change_url(person):
    return reverse("admin:people_person_change", args=[person.pk])


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.fixture
def parent_with_a_child(db):
    parent = Person.objects.create(
        last_name="Balicao", first_name="Juan",
        membership_status=MembershipStatus.MEMBER,
    )
    child = Person.objects.create(
        last_name="Balicao", first_name="Ana",
        membership_status=MembershipStatus.CHILD,
        date_of_birth=dt.date(2014, 1, 1),
        guardian=parent,
    )
    return parent, child


@pytest.mark.django_db
def test_a_parents_record_lists_their_children(client, parent_with_a_child):
    parent, child = parent_with_a_child
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(change_url(parent)).content.decode()

    assert "Children" in body or "children" in body
    assert "Ana" in body


@pytest.mark.django_db
def test_the_childs_fields_are_editable_not_just_shown(client, parent_with_a_child):
    parent, child = parent_with_a_child
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(change_url(parent)).content.decode()

    assert "wards-0-first_name" in body
    assert "wards-0-date_of_birth" in body


@pytest.mark.django_db
def test_somebody_elses_child_is_not_listed(client, parent_with_a_child):
    parent, _ = parent_with_a_child
    other = Person.objects.create(last_name="Reyes", first_name="Pedro")
    Person.objects.create(
        last_name="Reyes", first_name="Bea",
        membership_status=MembershipStatus.CHILD, guardian=other,
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(change_url(parent)).content.decode()

    assert "Bea" not in body


@pytest.mark.django_db
def test_a_chairperson_never_sees_the_children_inline(client, parent_with_a_child):
    """D12 withholds family from a chairperson, and get_inlines drops every
    inline for them -- this one must not become the exception."""
    parent, _ = parent_with_a_child
    user = make_user("chair", groups.CHAIRPERSON)
    chair = Person.objects.create(last_name="Chair", first_name="Sun", user=user)
    sunshine = Committee.objects.get(code="sunshine")
    for who, role in ((chair, CommitteeRole.CHAIRPERSON), (parent, CommitteeRole.MEMBER)):
        CommitteeMembership.objects.create(
            committee=sunshine, person=who, role=role,
            date_joined=dt.date.today() - dt.timedelta(days=30),
        )
    client.force_login(user)

    body = client.get(change_url(parent)).content.decode()

    assert "wards-0-first_name" not in body
    assert "Ana" not in body
