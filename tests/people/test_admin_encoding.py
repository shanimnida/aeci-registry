import datetime as dt

import pytest

from people.admin import find_possible_duplicates
from people.models import MembershipStatus, Person


@pytest.mark.django_db
def test_duplicates_are_found_by_name_and_birthdate():
    Person.objects.create(
        last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 3, 2)
    )
    candidate = Person(
        last_name="malong", first_name="SHAN", date_of_birth=dt.date(1995, 3, 2)
    )
    assert find_possible_duplicates(candidate).count() == 1


@pytest.mark.django_db
def test_a_shared_name_with_a_different_birthdate_is_not_a_duplicate():
    Person.objects.create(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1970, 1, 1)
    )
    candidate = Person(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1994, 9, 9)
    )
    assert find_possible_duplicates(candidate).count() == 0


@pytest.mark.django_db
def test_a_person_does_not_match_themselves():
    person = Person.objects.create(
        last_name="Reyes", first_name="Manex", date_of_birth=dt.date(1988, 7, 7)
    )
    assert find_possible_duplicates(person).count() == 0


@pytest.mark.django_db
def test_member_numbers_are_assigned_in_sequence_and_never_overwritten():
    from people.admin import assign_member_numbers

    existing = Person.objects.create(
        last_name="Daclitan",
        first_name="Kathleen",
        membership_status=MembershipStatus.MEMBER,
        member_no="MEM-0099",
    )
    fresh = Person.objects.create(
        last_name="Bilango", first_name="Alpha",
        membership_status=MembershipStatus.MEMBER,
    )

    assign_member_numbers(Person.objects.all())

    existing.refresh_from_db()
    fresh.refresh_from_db()
    assert existing.member_no == "MEM-0099"
    assert fresh.member_no == "MEM-0001"


@pytest.mark.django_db
def test_a_denied_view_is_not_logged(client):
    from django.contrib.auth.models import User
    from records.models import AccessLog

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    nosy = User.objects.create_user("nosy", password="x", is_staff=True)
    client.force_login(nosy)

    client.get(f"/admin/people/person/{person.pk}/change/")

    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_a_permitted_view_is_logged(client):
    from django.contrib.auth.models import Group, User
    from records.models import AccessLog
    from core import groups

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    secretary = User.objects.create_user("sec", password="x", is_staff=True)
    secretary.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    client.force_login(secretary)

    client.get(f"/admin/people/person/{person.pk}/change/")

    entry = AccessLog.objects.get()
    assert entry.user == secretary
    assert entry.person == person


@pytest.mark.django_db
def test_the_access_log_cannot_be_deleted_through_the_admin():
    from django.contrib.admin.sites import AdminSite
    from records.admin import AccessLogAdmin
    from records.models import AccessLog

    admin_obj = AccessLogAdmin(AccessLog, AdminSite())
    assert admin_obj.has_delete_permission(None) is False
