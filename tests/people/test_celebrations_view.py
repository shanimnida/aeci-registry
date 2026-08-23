"""The Celebrations screen: who may open it, what it renders, and the one
audit entry it writes.

tests/people/test_celebrations.py covers the date and exclusion logic
underneath. This file is about the page.

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
from people.models import Household, HouseholdMember, HouseholdRole, Person
from records.models import AccessLog

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()


def celebrations_url():
    return reverse("admin:people_person_celebrations")


def make_user(username, group_name=None):
    user = User.objects.create_user(username, password="x", is_staff=True)
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    return user


def make_chairperson(username, committee_code):
    """A chairperson-only user leading `committee_code`."""
    user = make_user(username, groups.CHAIRPERSON)
    person = Person.objects.create(last_name="Chair", first_name=username, user=user)
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code=committee_code),
        person=person,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    return user


def birthday_in(days, first_name="Ana", last_name="Reyes", **kwargs):
    """Someone whose birthday falls `days` from today, born in 1990."""
    when = TODAY + dt.timedelta(days=days)
    born = dt.date(1990, when.month, when.day) if (when.month, when.day) != (2, 29) else dt.date(1988, 2, 29)
    return Person.objects.create(
        last_name=last_name, first_name=first_name, date_of_birth=born, **kwargs
    )


# -- access (spec 7.7) --------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.SECRETARIAT, groups.ICT])
def test_the_secretariat_and_ict_can_open_it(client, group_name):
    client.force_login(make_user(f"u{group_name}", group_name))

    assert client.get(celebrations_url()).status_code == 200


@pytest.mark.django_db
def test_the_sunshine_chairperson_can_open_it(client):
    """Spec 7.7 names Sunshine's lead deliberately -- greetings and
    benevolence are that committee's actual job."""
    client.force_login(make_chairperson("sun", SUNSHINE_COMMITTEE_CODE))

    assert client.get(celebrations_url()).status_code == 200


@pytest.mark.django_db
def test_a_chairperson_of_another_committee_is_refused(client):
    client.force_login(make_chairperson("youthlead", "youth"))

    assert client.get(celebrations_url()).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.BOARD, None])
def test_roles_the_spec_does_not_list_are_refused(client, group_name):
    """Spec 7.7 lists the Secretariat, ICT and the Sunshine chairperson.
    The Board is not on it, and neither is an account with no role yet."""
    client.force_login(make_user(f"u{group_name}", group_name))

    assert client.get(celebrations_url()).status_code == 403


@pytest.mark.django_db
def test_a_former_sunshine_chairperson_loses_access(client):
    """Access follows the active roster, not a membership row that exists."""
    user = make_chairperson("expired", SUNSHINE_COMMITTEE_CODE)
    CommitteeMembership.objects.update(date_left=TODAY - dt.timedelta(days=1))
    client.force_login(user)

    assert client.get(celebrations_url()).status_code == 403


@pytest.mark.django_db
def test_anonymous_is_sent_to_the_login_page(client):
    response = client.get(celebrations_url())

    assert response.status_code == 302
    assert "/login/" in response["Location"]


# -- what it renders ----------------------------------------------------


@pytest.mark.django_db
def test_it_lists_an_upcoming_birthday_and_anniversary(client):
    birthday_in(5, first_name="Ana", last_name="Reyes")
    when = TODAY + dt.timedelta(days=6)
    household = Household.objects.create(
        name="Dizon Family", date_of_marriage=dt.date(2010, when.month, when.day)
    )
    head = Person.objects.create(last_name="Dizon", first_name="Nonoy")
    HouseholdMember.objects.create(
        household=household, person=head, role=HouseholdRole.HEAD
    )

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(celebrations_url()).content.decode()

    assert "Ana" in body
    assert "Nonoy" in body


@pytest.mark.django_db
def test_no_birth_year_and_no_age_ever_reaches_the_page(client):
    """D17. The whole reason this list shows month and day only."""
    Person.objects.create(
        last_name="Reyes",
        first_name="Ana",
        date_of_birth=dt.date(1990, TODAY.month, TODAY.day),
    )

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(celebrations_url()).content.decode()

    assert "Ana" in body
    assert "1990" not in body


@pytest.mark.django_db
def test_the_ready_to_post_greeting_is_on_the_page(client):
    birthday_in(3, first_name="Ana")
    birthday_in(4, first_name="Ben", last_name="Cruz")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(celebrations_url()).content.decode()

    assert "Happy birthday, Ana and Ben!" in body


@pytest.mark.django_db
def test_the_missing_birthdate_count_is_shown_as_a_standing_argument(client):
    """Spec 7.1: people with no birthdate cannot appear here, which is what
    makes this page an argument for working the follow-up queue."""
    Person.objects.create(last_name="Torres", first_name="Blank")
    Person.objects.create(last_name="Torres", first_name="Also")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    body = client.get(celebrations_url()).content.decode()

    assert "2" in body
    assert reverse("admin:people_person_missing_data") in body


@pytest.mark.django_db
def test_an_empty_window_renders_a_message_not_a_broken_table(client):
    client.force_login(make_user("sec", groups.SECRETARIAT))
    response = client.get(celebrations_url())

    assert response.status_code == 200
    assert "No birthdays" in response.content.decode()


@pytest.mark.django_db
def test_the_period_can_be_changed_from_the_query_string(client):
    """A church works to a weekly rhythm and plans to a monthly one, so the
    Show buttons offer this week, this month and next month rather than a
    count of days."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    for period in ("week", "month", "next-month"):
        assert client.get(celebrations_url(), {"period": period}).status_code == 200


@pytest.mark.django_db
def test_this_week_is_narrower_than_this_month(client):
    """Somebody whose birthday is late in the month is on the month view and
    not on the week view -- unless the month happens to be nearly over, so
    this asserts the relationship rather than a fixed date."""
    from people.celebrations import period_bounds

    week_first, week_last, _ = period_bounds("week")
    month_first, month_last, _ = period_bounds("month")

    assert (week_last - week_first).days == 6
    assert month_first <= month_last
    assert (month_last - month_first).days >= 27


@pytest.mark.django_db
def test_a_nonsense_period_falls_back_instead_of_erroring(client):
    """A hand-edited URL is not worth a 500 on a page the Secretariat opens
    every Sunday."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    assert client.get(celebrations_url(), {"period": "banana"}).status_code == 200
    assert client.get(celebrations_url(), {"period": ""}).status_code == 200


# -- audit (spec 7.6) ---------------------------------------------------


@pytest.mark.django_db
def test_one_access_log_entry_is_written_for_the_whole_report(client):
    """A report listing thirty people writes one entry naming the report,
    not thirty. Logging every row buries the signal the log exists for."""
    for index in range(3):
        birthday_in(index + 1, first_name=f"P{index}")

    client.force_login(make_user("sec", groups.SECRETARIAT))
    client.get(celebrations_url())

    assert AccessLog.objects.count() == 1
    entry = AccessLog.objects.get()
    assert entry.person is None
    assert "celebrations" in entry.report.lower()


@pytest.mark.django_db
def test_a_refused_user_leaves_no_log_entry(client):
    """R15's rule: for a log whose purpose is answering an RA 10173
    complaint, a false entry is worse than a missing one."""
    client.force_login(make_user("norole", None))
    client.get(celebrations_url())

    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_no_template_comment_leaks_into_either_page(client):
    """Django's {# #} comment is single-line only: a multi-line one is not
    recognised as a comment token at all and renders as literal text on the
    page. Both of these templates carry long explanatory comments, so this
    guards the whole class rather than one instance."""
    birthday_in(2, first_name="Ana")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    for url in (celebrations_url(), reverse("admin:index")):
        body = client.get(url).content.decode()
        assert "{#" not in body, url
        assert "#}" not in body, url
