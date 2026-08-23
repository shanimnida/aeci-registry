"""Read-only Person and Household pages, added 2026-08-24.

Clicking a name used to open the edit form. It now opens a page built for
reading, with Edit one button away for whoever holds the permission.

The point of most of these tests is the same as R18's: a NEW page that
renders a person's record is exactly the shape of thing that leaked last
time. A chairperson must see the same five fields here as everywhere else,
and nothing about anyone off their roster.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.utils import timezone
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)
from records.models import AccessLog

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()


def person_view_url(person):
    return reverse("admin:people_person_view", args=[person.pk])


def household_view_url(household):
    return reverse("admin:people_household_view", args=[household.pk])


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.fixture
def maria(db):
    return Person.objects.create(
        last_name="Balicao",
        first_name="Maria Clara",
        nickname="Baby",
        member_no="MEM-0042",
        membership_status=MembershipStatus.MEMBER,
        date_of_birth=dt.date(1985, 3, 12),
        home_address="12 Fictional Road, La Trinidad",
        mobile_number="09171234567",
        email="baby@example.com",
        civil_status="MARRIED",
    )


# -- the page ----------------------------------------------------------


@pytest.mark.django_db
def test_the_page_leads_with_who_they_are_and_how_to_reach_them(client, maria):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(person_view_url(maria)).content.decode()

    assert "Maria Clara Balicao" in body
    assert "Baby" in body
    assert "MEM-0042" in body
    assert "09171234567" in body
    assert "baby@example.com" in body


@pytest.mark.django_db
def test_the_family_is_listed_with_a_link_to_each_person(client, maria):
    household = Household.objects.create(name="Balicao Family")
    child = Person.objects.create(
        last_name="Balicao", first_name="Miguel", membership_status=MembershipStatus.CHILD
    )
    HouseholdMember.objects.create(
        household=household, person=maria, role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=household, person=child, role=HouseholdRole.CHILD
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(person_view_url(maria)).content.decode()

    assert "Balicao Family" in body
    assert person_view_url(child) in body
    assert household_view_url(household) in body


@pytest.mark.django_db
def test_committees_are_shown_with_role_and_since_when(client, maria):
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=maria,
        role=CommitteeRole.SECRETARY,
        date_joined=TODAY - dt.timedelta(days=10),
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(person_view_url(maria)).content.decode()

    assert "Sunshine" in body
    assert "Secretary" in body


@pytest.mark.django_db
def test_missing_fields_read_as_a_task_not_a_blank(client):
    """Half the register is incomplete by design (spec 6.3), so an absence
    here is something to chase, not an empty cell."""
    person = Person.objects.create(last_name="Torres", first_name="Blank")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(person_view_url(person)).content.decode()

    assert "Needs follow-up" in body


@pytest.mark.django_db
def test_a_complete_record_shows_no_follow_up_banner(client, maria):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    assert "Needs follow-up" not in client.get(person_view_url(maria)).content.decode()


# -- the edit button ---------------------------------------------------


@pytest.mark.django_db
def test_edit_is_offered_to_someone_who_can_edit(client, maria):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(person_view_url(maria)).content.decode()

    assert reverse("admin:people_person_change", args=[maria.pk]) in body


@pytest.mark.django_db
def test_edit_is_absent_for_someone_who_cannot(client, maria):
    """A button that would only 403 them is a dead end, not a feature."""
    board = make_user("board", groups.BOARD)
    board.user_permissions.clear()
    board.groups.clear()
    board.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=Person.objects.create(last_name="Chair", first_name="Sun", user=board),
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=maria,
        role=CommitteeRole.MEMBER,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    client.force_login(board)

    body = client.get(person_view_url(maria)).content.decode()

    assert reverse("admin:people_person_change", args=[maria.pk]) not in body


# -- chairperson scoping (D12, and the R18 leak this page could reopen) --


@pytest.fixture
def sunshine_chair(db):
    user = make_user("chair", groups.CHAIRPERSON)
    Person.objects.create(last_name="Chair", first_name="Sun", user=user)
    return user


def put_on_sunshine(person):
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=person,
        role=CommitteeRole.MEMBER,
        date_joined=TODAY - dt.timedelta(days=30),
    )


@pytest.mark.django_db
def test_a_chairperson_sees_only_the_five_permitted_fields(client, sunshine_chair, maria):
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=Person.objects.get(user=sunshine_chair),
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    put_on_sunshine(maria)
    household = Household.objects.create(name="Balicao Family")
    HouseholdMember.objects.create(
        household=household, person=maria, role=HouseholdRole.HEAD
    )
    client.force_login(sunshine_chair)

    body = client.get(person_view_url(maria)).content.decode()

    # The five they may see.
    assert "Maria Clara" in body
    assert "Baby" in body
    assert "09171234567" in body
    assert "baby@example.com" in body
    # Everything D12 withholds.
    assert "12 Fictional Road" not in body
    assert "Married" not in body
    assert "Balicao Family" not in body
    assert "1985" not in body


@pytest.mark.django_db
def test_a_chairperson_gets_a_404_for_someone_off_their_roster(client, sunshine_chair, maria):
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="sunshine"),
        person=Person.objects.get(user=sunshine_chair),
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    client.force_login(sunshine_chair)

    assert client.get(person_view_url(maria)).status_code == 404


@pytest.mark.django_db
def test_anonymous_is_sent_to_the_login_page(client, maria):
    response = client.get(person_view_url(maria))

    assert response.status_code == 302
    assert "/login/" in response["Location"]


# -- audit -------------------------------------------------------------


@pytest.mark.django_db
def test_viewing_a_person_is_written_to_the_access_log(client, maria):
    """The whole point of AccessLog under RA 10173. Viewing moved to a new
    page, so the logging had to move with it."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    client.get(person_view_url(maria))

    entry = AccessLog.objects.get()
    assert entry.person == maria


@pytest.mark.django_db
def test_a_household_view_writes_one_entry_naming_the_household(client, maria):
    """Not one per member (spec 7.6)."""
    household = Household.objects.create(name="Balicao Family")
    for index in range(3):
        HouseholdMember.objects.create(
            household=household,
            person=Person.objects.create(last_name="Balicao", first_name=f"P{index}"),
            role=HouseholdRole.CHILD,
        )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    client.get(household_view_url(household))

    assert AccessLog.objects.count() == 1
    entry = AccessLog.objects.get()
    assert entry.person is None
    assert "Balicao Family" in entry.report


# -- households --------------------------------------------------------


@pytest.mark.django_db
def test_a_household_lists_its_members_with_links(client, maria):
    household = Household.objects.create(
        name="Balicao Family",
        address="12 Fictional Road, La Trinidad",
        date_of_marriage=dt.date(2010, 2, 4),
    )
    HouseholdMember.objects.create(
        household=household, person=maria, role=HouseholdRole.HEAD
    )
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(household_view_url(household)).content.decode()

    assert "Balicao Family" in body
    assert "12 Fictional Road" in body
    assert person_view_url(maria) in body
    assert "Head" in body


@pytest.mark.django_db
def test_an_empty_household_says_so_instead_of_rendering_nothing(client):
    household = Household.objects.create(name="Empty Family")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(household_view_url(household)).content.decode()

    assert "Nobody is recorded in this household yet" in body


@pytest.mark.django_db
def test_a_chairperson_cannot_reach_a_household_at_all(client, sunshine_chair):
    """The Chairperson group holds no view_household permission -- a
    household is precisely what D12 withholds."""
    household = Household.objects.create(name="Balicao Family")
    client.force_login(sunshine_chair)

    assert client.get(household_view_url(household)).status_code == 403


# -- the changelist now points here ------------------------------------


@pytest.mark.django_db
def test_the_people_list_links_names_to_the_view_page(client, maria):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(reverse("admin:people_person_changelist")).content.decode()

    assert person_view_url(maria) in body
    assert reverse("admin:people_person_change", args=[maria.pk]) not in body


@pytest.mark.django_db
def test_the_household_list_links_names_to_the_view_page(client):
    household = Household.objects.create(name="Balicao Family")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(reverse("admin:people_household_changelist")).content.decode()

    assert household_view_url(household) in body
