"""The Celebrations panel on the admin landing page.

The panel reuses the full report's access gate. These tests exist mostly
to prove that: a Treasurer getting a 403 on the full page while the same
data sits on the dashboard they land on would make the 403 decoration.

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
from people.celebrations import SUNSHINE_COMMITTEE_CODE
from people.models import Person
from records.models import AccessLog

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()


def index_url():
    return reverse("admin:index")


def make_user(username, group_name=None):
    user = User.objects.create_user(username, password="x", is_staff=True)
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    return user


def birthday_in(days, first_name):
    when = TODAY + dt.timedelta(days=days)
    if (when.month, when.day) == (2, 29):
        born = dt.date(1988, 2, 29)
    else:
        born = dt.date(1990, when.month, when.day)
    return Person.objects.create(
        last_name="Delacruz", first_name=first_name, date_of_birth=born
    )


@pytest.mark.django_db
def test_the_week_appears_on_the_dashboard_for_the_secretariat(client):
    birthday_in(2, "Ana")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(index_url()).content.decode()

    assert "This week" in body
    assert "Ana" in body


@pytest.mark.django_db
def test_a_birthday_beyond_the_week_is_not_on_the_dashboard(client):
    birthday_in(20, "Faraway")

    client.force_login(make_user("sec", groups.SECRETARIAT))

    assert "Faraway" not in client.get(index_url()).content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.TREASURER, groups.BOARD])
def test_a_role_refused_the_report_does_not_get_it_on_the_dashboard(client, group_name):
    """Otherwise the 403 on the full page is decoration."""
    birthday_in(2, "Ana")

    client.force_login(make_user(f"u{group_name}", group_name))
    body = client.get(index_url()).content.decode()

    assert "This week" not in body
    assert "Ana" not in body


@pytest.mark.django_db
def test_the_sunshine_chairperson_gets_the_panel(client):
    birthday_in(2, "Ana")
    user = make_user("sun", groups.CHAIRPERSON)
    person = Person.objects.create(last_name="Chair", first_name="Sun", user=user)
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code=SUNSHINE_COMMITTEE_CODE),
        person=person,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )

    client.force_login(user)
    body = client.get(index_url()).content.decode()

    assert "This week" in body
    assert "Ana" in body


@pytest.mark.django_db
def test_a_quiet_week_shows_no_empty_panel(client):
    client.force_login(make_user("sec", groups.SECRETARIAT))

    assert "This week" not in client.get(index_url()).content.decode()


@pytest.mark.django_db
def test_the_dashboard_panel_writes_no_access_log_entry(client):
    """Deliberate -- see people/dashboard.py. This callback runs on every
    load of the admin index, so logging it would put a row in the audit log
    each time anyone opens AEGIS at all, burying the signal spec 7.6 exists
    to protect. The full report, where the work actually happens, is logged.
    """
    birthday_in(2, "Ana")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    client.get(index_url())

    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_the_panel_links_through_to_the_full_report(client):
    birthday_in(2, "Ana")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(index_url()).content.decode()

    assert reverse("admin:people_person_celebrations") in body


@pytest.mark.django_db
def test_the_dashboard_still_renders_the_app_list_underneath(client):
    """The index template shadows Unfold's own -- if that override ever
    drops one of Unfold's includes, the admin loses its app list and this
    is what catches it."""
    client.force_login(make_user("ict", groups.ICT))
    body = client.get(index_url()).content.decode()

    assert reverse("admin:people_person_changelist") in body
