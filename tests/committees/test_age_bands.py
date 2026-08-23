"""The Board's age bands and the committee places that follow from them,
decided by the Board and recorded 2026-08-24.

    children  0–12   -> Children's Ministry
    juniors   13–15  -> Youth committee, marked as juniors
    youths    16–30  -> Youth committee

Nothing here writes a membership row. The place is computed, so somebody
joins Youth on their thirteenth birthday and leaves after their
thirty-first without a job running or a row appearing under a name nobody
typed.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from committees.derived import derived_places, unplaceable_count
from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.agebands import AgeBand, age_on, band_for
from people.models import MembershipStatus, Person

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()


def born_years_ago(years, days=0):
    """A birthdate that makes somebody exactly `years` old today."""
    try:
        birthday = TODAY.replace(year=TODAY.year - years)
    except ValueError:  # 29 February
        birthday = TODAY.replace(year=TODAY.year - years, day=28)
    return birthday - dt.timedelta(days=days)


def person_aged(years, first_name="Anon", **kwargs):
    return Person.objects.create(
        last_name="Pucay",
        first_name=first_name,
        date_of_birth=born_years_ago(years),
        **kwargs,
    )


def committee(code):
    return Committee.objects.get(code=code)


# -- the arithmetic ----------------------------------------------------


def test_age_is_whole_years_and_turns_over_on_the_birthday():
    born = dt.date(2010, 6, 15)

    assert age_on(born, dt.date(2026, 6, 14)) == 15
    assert age_on(born, dt.date(2026, 6, 15)) == 16
    assert age_on(born, dt.date(2026, 6, 16)) == 16


def test_a_missing_birthdate_has_no_age_and_no_band():
    assert age_on(None) is None
    assert band_for(None) is None


def test_a_birthdate_in_the_future_has_no_age():
    assert age_on(TODAY + dt.timedelta(days=1)) is None


@pytest.mark.parametrize(
    "age,expected",
    [
        (0, AgeBand.CHILD), (12, AgeBand.CHILD),
        (13, AgeBand.JUNIOR), (15, AgeBand.JUNIOR),
        (16, AgeBand.YOUTH), (30, AgeBand.YOUTH),
    ],
)
def test_each_boundary_falls_in_the_band_the_board_named(age, expected):
    assert band_for(born_years_ago(age)) == expected


@pytest.mark.parametrize("age", [31, 45, 80])
def test_nobody_over_thirty_is_in_a_band(age):
    """The Board named three bands. AEGIS does not invent a fourth."""
    assert band_for(born_years_ago(age)) is None


# -- the places that follow --------------------------------------------


@pytest.mark.django_db
def test_a_child_is_placed_on_the_childrens_ministry():
    child = person_aged(7, "Bita")

    places = derived_places(committee("childrens-ministry"))

    assert [place.person for place in places] == [child]


@pytest.mark.django_db
def test_a_junior_is_on_youth_and_marked_as_a_junior():
    """The Board's words: juniors are members of the youth, but still mark
    them as juniors."""
    junior = person_aged(14, "Ligaya")

    place = derived_places(committee("youth"))[0]

    assert place.person == junior
    assert place.band == AgeBand.JUNIOR
    assert place.function_name == "Juniors"


@pytest.mark.django_db
def test_a_youth_is_on_youth_with_no_sub_team():
    person_aged(22, "Tala")

    place = derived_places(committee("youth"))[0]

    assert place.band == AgeBand.YOUTH
    assert place.function_name == ""


@pytest.mark.django_db
def test_juniors_and_youths_share_the_youth_committee():
    person_aged(14, "Ligaya")
    person_aged(22, "Tala")

    assert len(derived_places(committee("youth"))) == 2


@pytest.mark.django_db
def test_a_child_is_not_on_youth_and_a_youth_is_not_on_childrens_ministry():
    person_aged(7, "Bita")
    person_aged(22, "Tala")

    assert len(derived_places(committee("youth"))) == 1
    assert len(derived_places(committee("childrens-ministry"))) == 1


@pytest.mark.django_db
def test_a_committee_the_rule_says_nothing_about_gets_no_derived_places():
    person_aged(22, "Tala")

    assert derived_places(committee("food")) == []


@pytest.mark.django_db
def test_somebody_with_no_birthdate_is_not_placed():
    Person.objects.create(last_name="Pucay", first_name="Unknown")

    assert derived_places(committee("youth")) == []
    assert unplaceable_count() == 1


@pytest.mark.django_db
def test_a_transferred_or_deceased_person_is_not_swept_back_by_a_birthday():
    person_aged(22, "Gone", membership_status=MembershipStatus.TRANSFERRED)
    person_aged(22, "Late", date_of_death=TODAY - dt.timedelta(days=30))

    assert derived_places(committee("youth")) == []


@pytest.mark.django_db
def test_a_real_membership_wins_over_the_age_rule():
    """Somebody recorded as chairing Youth must appear once, as its
    chairperson -- not twice, once as an ordinary member by age."""
    chair = person_aged(20, "Tala")
    CommitteeMembership.objects.create(
        committee=committee("youth"),
        person=chair,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )

    places = derived_places(committee("youth"), exclude_person_ids={chair.pk})

    assert places == []


@pytest.mark.django_db
def test_the_boundary_moves_on_its_own_the_day_after_a_birthday(settings):
    """Nobody has to run anything. Somebody who turns 31 today is out; a
    day earlier they were in."""
    just_turned_31 = person_aged(31, "Older")
    still_30 = Person.objects.create(
        last_name="Pucay",
        first_name="Younger",
        date_of_birth=born_years_ago(31) + dt.timedelta(days=1),
    )

    people = [place.person for place in derived_places(committee("youth"))]

    assert still_30 in people
    assert just_turned_31 not in people


# -- how it reads on the roster ----------------------------------------


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.mark.django_db
def test_the_roster_shows_a_derived_place_and_says_it_is_by_age(client):
    person_aged(14, "Ligaya")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(
        reverse(
            "admin:committees_committeemembership_overview_detail",
            args=[committee("youth").pk],
        )
    ).content.decode()

    assert "Ligaya" in body
    assert "by age" in body
    assert "Juniors" in body


@pytest.mark.django_db
def test_the_roster_says_how_many_cannot_be_placed(client):
    Person.objects.create(last_name="Pucay", first_name="Unknown")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(
        reverse(
            "admin:committees_committeemembership_overview_detail",
            args=[committee("youth").pk],
        )
    ).content.decode()

    assert "no birthdate on file" in body


@pytest.mark.django_db
def test_the_overview_counts_derived_places(client):
    person_aged(14, "Ligaya")
    person_aged(22, "Tala")
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(
        reverse("admin:committees_committeemembership_overview")
    ).content.decode()

    assert "Youth" in body


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_recorded_roster_not_the_age_rule(client):
    """A chairperson's view is scoped to people they were actually given.
    Adding an age-derived list would hand them the congregation."""
    user = make_user("chair", groups.CHAIRPERSON)
    chair_person = Person.objects.create(last_name="Chair", first_name="Yut", user=user)
    CommitteeMembership.objects.create(
        committee=committee("youth"),
        person=chair_person,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=30),
    )
    person_aged(14, "Ligaya")
    client.force_login(user)

    body = client.get(
        reverse(
            "admin:committees_committeemembership_overview_detail",
            args=[committee("youth").pk],
        )
    ).content.decode()

    assert "Ligaya" not in body
