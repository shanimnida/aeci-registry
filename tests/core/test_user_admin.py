"""The account screens ICT uses to create logins.

Reworked 2026-08-24 after the church called the stock permission picker
"too hard and taxing to read". It was, but the reason it goes rather than
gets restyled is that AEGIS grants nothing to individuals: every capability
in spec 4 belongs to one of five groups. A per-user grant could only ever
give somebody access their role does not have — invisible to any group
audit, read by nothing in this project, and surviving a move between
groups.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse

from core import groups


@pytest.fixture
def ict(db):
    user = User.objects.create_user(
        "ict", password="x", is_staff=True, is_superuser=True
    )
    user.groups.add(Group.objects.get(name=groups.ICT))
    return user


@pytest.fixture
def volunteer(db):
    return User.objects.create_user("mabel", password="x", is_staff=True)


def change_url(user):
    return reverse("admin:auth_user_change", args=[user.pk])


# -- the picker is gone ------------------------------------------------


@pytest.mark.django_db
def test_the_per_user_permission_picker_is_not_on_the_form(client, ict, volunteer):
    """Sixty rows of "Committees | church position | Can add appointment" in
    a dual-list widget, for a field this design never uses."""
    client.force_login(ict)

    body = client.get(change_url(volunteer)).content.decode()

    assert "Available user permissions" not in body
    assert 'name="user_permissions"' not in body


@pytest.mark.django_db
def test_groups_are_plain_checkboxes(client, ict, volunteer):
    """Five roles with real names. A filter-and-shuttle widget in front of
    five checkboxes is machinery standing in front of a simple question."""
    client.force_login(ict)

    body = client.get(change_url(volunteer)).content.decode()

    assert 'type="checkbox" name="groups"' in body or 'name="groups"' in body
    assert "Choose all user permissions" not in body


@pytest.mark.django_db
def test_a_group_can_still_be_assigned(client, ict, volunteer):
    """The one thing this screen is actually for."""
    client.force_login(ict)
    secretariat = Group.objects.get(name=groups.SECRETARIAT)

    client.post(
        change_url(volunteer),
        {
            "username": volunteer.username,
            "first_name": "",
            "last_name": "",
            "email": "",
            "is_active": "on",
            "is_staff": "on",
            "groups": [secretariat.pk],
            "last_login_0": "",
            "last_login_1": "",
            "date_joined_0": "2026-08-01",
            "date_joined_1": "00:00:00",
        },
        follow=True,
    )

    volunteer.refresh_from_db()
    assert list(volunteer.groups.values_list("name", flat=True)) == [groups.SECRETARIAT]


# -- but an existing grant is not hidden -------------------------------


@pytest.mark.django_db
def test_an_account_with_no_individual_grants_says_so_plainly(client, ict, volunteer):
    client.force_login(ict)

    body = client.get(change_url(volunteer)).content.decode()

    assert "comes entirely from its group" in body


@pytest.mark.django_db
def test_a_permission_already_granted_directly_is_named_not_hidden(
    client, ict, volunteer
):
    """Removing the picker must not make an existing grant invisible.
    Access nobody can see is worse than access that is awkward to edit."""
    volunteer.user_permissions.add(Permission.objects.get(codename="delete_person"))
    client.force_login(ict)

    body = client.get(change_url(volunteer)).content.decode()

    assert "delete_person" in body
    assert "outside any group" in body


# -- the rest of the screen --------------------------------------------


@pytest.mark.django_db
def test_the_changelist_names_each_accounts_role(client, ict, volunteer):
    volunteer.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    client.force_login(ict)

    body = client.get(reverse("admin:auth_user_changelist")).content.decode()

    assert groups.CHAIRPERSON in body
    assert "Superuser" in body  # the ICT account itself


@pytest.mark.django_db
def test_the_add_page_warns_about_the_thing_everyone_forgets(client, ict):
    """docs/DEPLOYMENT.md section 7 calls staff status the single most
    common thing to forget, and a doc is not where somebody looks
    mid-task."""
    client.force_login(ict)

    body = client.get(reverse("admin:auth_user_add")).content.decode()

    assert "Staff status" in body


@pytest.mark.django_db
def test_the_superuser_warning_is_on_the_page_that_grants_it(client, ict, volunteer):
    client.force_login(ict)

    body = client.get(change_url(volunteer)).content.decode()

    assert "bypasses every permission check" in body
