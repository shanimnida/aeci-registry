import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import Person
from records.models import AccessLog

TODAY = dt.date.today()
JOINED = TODAY - dt.timedelta(days=7)


def missing_data_url():
    return reverse("admin:people_person_missing_data")


# A person with every TRACKED_FIELDS gap filled in -- has_missing_data is
# False, so this person must never appear on the chase list.
COMPLETE_FIELDS = dict(
    date_of_birth=TODAY - dt.timedelta(days=365 * 30),
    mobile_number="09171234567",
    email="complete@example.com",
    home_address="123 Example Street, Example City",
    civil_status="SINGLE",
)


def make_secretariat_user(username="sec"):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.mark.django_db
def test_lists_a_person_with_blanks_and_names_exactly_the_blanks(client):
    Person.objects.create(last_name="Reyes", first_name="Manex")
    Person.objects.create(last_name="Santos", first_name="Rhea", **COMPLETE_FIELDS)

    client.force_login(make_secretariat_user())
    response = client.get(missing_data_url())
    body = response.content.decode()

    assert response.status_code == 200
    assert "Manex Reyes" in body
    for label in ("Date of birth", "Mobile number", "Email", "Home address", "Civil status"):
        assert label in body


@pytest.mark.django_db
def test_a_person_with_nothing_missing_does_not_appear(client):
    Person.objects.create(last_name="Santos", first_name="Rhea", **COMPLETE_FIELDS)

    client.force_login(make_secretariat_user())
    response = client.get(missing_data_url())
    body = response.content.decode()

    assert "Rhea Santos" not in body
    assert "Nobody outstanding" in body


@pytest.mark.django_db
def test_an_empty_report_renders_a_message_not_a_broken_table(client):
    client.force_login(make_secretariat_user())
    response = client.get(missing_data_url())

    assert response.status_code == 200
    assert "Nobody outstanding" in response.content.decode()


@pytest.mark.django_db
def test_an_anonymous_request_is_refused(client):
    response = client.get(missing_data_url())
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_a_treasurer_is_refused(client):
    """Treasurer holds no Person permissions at all (spec section 4,
    core/migrations/0002_create_groups.py) -- the report must not widen
    that."""
    user = User.objects.create_user("treasurer", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.TREASURER))
    client.force_login(user)
    response = client.get(missing_data_url())
    assert response.status_code == 403


@pytest.mark.django_db
def test_the_board_sees_everyone(client):
    """Board already sees every Person through the ordinary changelist
    (core/migrations/0002_create_groups.py grants view_person, and Board is
    a WIDER_ACCESS_GROUPS member so it is never chairperson-scoped) -- the
    report must match that, not narrow or widen it."""
    Person.objects.create(last_name="Reyes", first_name="Manex")
    user = User.objects.create_user("board", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.BOARD))
    client.force_login(user)
    response = client.get(missing_data_url())
    assert response.status_code == 200
    assert "Manex Reyes" in response.content.decode()


@pytest.mark.django_db
def test_an_accesslog_entry_is_written_once_per_view(client):
    Person.objects.create(last_name="Reyes", first_name="Manex")
    client.force_login(make_secretariat_user())

    assert AccessLog.objects.count() == 0
    client.get(missing_data_url())
    assert AccessLog.objects.count() == 1

    entry = AccessLog.objects.get()
    assert entry.person is None
    assert entry.report  # a list, not a single person -- see AccessLog.record


@pytest.mark.django_db
def test_the_changelist_links_to_the_report(client):
    client.force_login(make_secretariat_user())
    response = client.get(reverse("admin:people_person_changelist"))
    assert missing_data_url() in response.content.decode()


@pytest.mark.django_db
def test_the_committee_filter_narrows_to_one_committees_people(client):
    """Splitting the work: a chairperson chasing their own people, or the
    Secretariat handing two volunteers two separate committees' pages."""
    sunshine = Committee.objects.get(code="sunshine")
    food = Committee.objects.get(code="food")
    sunshine_person = Person.objects.create(last_name="Reyes", first_name="Manex")
    food_person = Person.objects.create(last_name="Santos", first_name="Rhea")
    CommitteeMembership.objects.create(
        committee=sunshine, person=sunshine_person, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=food, person=food_person, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    client.force_login(make_secretariat_user())
    response = client.get(missing_data_url(), {"committee": sunshine.pk})
    body = response.content.decode()

    assert "Manex Reyes" in body
    assert "Rhea Santos" not in body


@pytest.fixture
def chair_setup(db):
    # mobile_number/email filled so the chairperson's own record -- part of
    # its own roster, since chairing a committee is itself a membership row
    # -- never shows up as outstanding and adds noise to these assertions.
    # date_of_birth/home_address/civil_status are deliberately left blank:
    # irrelevant here, since those fields never surface in a chairperson's
    # own report either way.
    chair_person = Person.objects.create(
        last_name="Malong", first_name="Shan",
        mobile_number="09170000001", email="shan@example.com",
    )
    ict = Committee.objects.get(code="ict")
    CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
    )
    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, ict


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committee(client, chair_setup):
    user, ict = chair_setup
    food = Committee.objects.get(code="food")

    mine = Person.objects.create(last_name="Reyes", first_name="Manex")
    stranger = Person.objects.create(last_name="Santos", first_name="Rhea")
    CommitteeMembership.objects.create(
        committee=ict, person=mine, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    client.force_login(user)
    response = client.get(missing_data_url())
    body = response.content.decode()

    assert "Manex Reyes" in body
    assert "Rhea Santos" not in body


@pytest.mark.django_db
def test_a_chairperson_never_sees_a_person_whose_only_gap_is_withheld(client, chair_setup):
    """Missing only home_address -- a field CHAIRPERSON_FIELDS never shows.
    The person must not appear at all: showing them with zero visible
    missing fields would itself disclose that a withheld field is blank."""
    user, ict = chair_setup
    fields = dict(COMPLETE_FIELDS)
    del fields["home_address"]
    only_address_missing = Person.objects.create(
        last_name="Cruz", first_name="Dela", **fields
    )
    CommitteeMembership.objects.create(
        committee=ict, person=only_address_missing, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    assert only_address_missing.has_missing_data

    client.force_login(user)
    response = client.get(missing_data_url())
    body = response.content.decode()

    assert "Dela Cruz" not in body
    assert "Nobody outstanding" in body


@pytest.mark.django_db
def test_a_chairperson_sees_no_withheld_field_names(client, chair_setup):
    """This person is missing a mobile number (visible to a chairperson)
    *and* a home address (not). Only "Mobile number" may surface -- never
    "Home address", "Date of birth" or "Civil status", anywhere on the
    page, for anyone."""
    user, ict = chair_setup
    fields = dict(COMPLETE_FIELDS)
    del fields["mobile_number"]
    del fields["home_address"]
    person = Person.objects.create(last_name="Cruz", first_name="Dela", **fields)
    CommitteeMembership.objects.create(
        committee=ict, person=person, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    client.force_login(user)
    response = client.get(missing_data_url())
    body = response.content.decode()

    assert "Dela Cruz" in body
    assert "Mobile number" in body
    for withheld in ("Home address", "Date of birth", "Civil status"):
        assert withheld not in body
