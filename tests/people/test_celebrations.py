"""Spec 7.1: upcoming birthdays and wedding anniversaries, the Church
Secretary's original reason for asking for AEGIS at all.

These tests drive people/celebrations.py directly -- the pure date and
exclusion logic, with no HTTP -- so the awkward cases (a window crossing
the year end, 29 February in a common year) are exercised where they can
be read. tests/people/test_celebrations_view.py covers the admin screen,
its permissions and its audit entry.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest

from people.celebrations import (
    ANNIVERSARY_GREETING,
    BIRTHDAY_GREETING,
    combined_anniversary_greeting,
    combined_birthday_greeting,
    missing_birthdate_count,
    upcoming_anniversaries,
    upcoming_birthdays,
)
from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)


def make_person(first_name, last_name, born=None, **kwargs):
    return Person.objects.create(
        first_name=first_name, last_name=last_name, date_of_birth=born, **kwargs
    )


def make_couple(surname, married_on, head_kwargs=None, spouse_kwargs=None, with_spouse=True):
    household = Household.objects.create(
        name=f"{surname} Family", date_of_marriage=married_on
    )
    head = make_person("Head", surname, **(head_kwargs or {}))
    HouseholdMember.objects.create(
        household=household, person=head, role=HouseholdRole.HEAD
    )
    if with_spouse:
        spouse = make_person("Spouse", surname, **(spouse_kwargs or {}))
        HouseholdMember.objects.create(
            household=household, person=spouse, role=HouseholdRole.SPOUSE
        )
    return household


# -- the window ---------------------------------------------------------


@pytest.mark.django_db
def test_a_birthday_inside_the_window_appears_and_one_outside_does_not():
    start = dt.date(2026, 6, 1)
    make_person("Ana", "Reyes", born=dt.date(1990, 6, 10))  # 9 days away
    make_person("Ben", "Cruz", born=dt.date(1988, 9, 10))  # months away

    entries = upcoming_birthdays(start=start, days=30)

    assert [entry.subtitle for entry in entries] == ["Ana Reyes"]


@pytest.mark.django_db
def test_the_window_includes_both_its_endpoints():
    start = dt.date(2026, 6, 1)
    make_person("Today", "Santos", born=dt.date(1990, 6, 1))
    make_person("Last", "Santos", born=dt.date(1990, 7, 1))  # start + 30
    make_person("Just", "Santos", born=dt.date(1990, 7, 2))  # start + 31

    names = [entry.names for entry in upcoming_birthdays(start=start, days=30)]

    assert names == ["Today", "Last"]


@pytest.mark.django_db
def test_the_window_crosses_the_year_end():
    """A 30-day window opened in December must reach into January. Sorting
    has to follow, or the January entries pile up before the December ones."""
    start = dt.date(2026, 12, 20)
    make_person("Dec", "Lim", born=dt.date(1990, 12, 28))
    make_person("Jan", "Lim", born=dt.date(1990, 1, 5))
    make_person("Feb", "Lim", born=dt.date(1990, 2, 20))  # outside

    entries = upcoming_birthdays(start=start, days=30)

    assert [entry.names for entry in entries] == ["Dec", "Jan"]


@pytest.mark.django_db
def test_a_29_february_birthday_is_greeted_on_1_march_in_a_common_year():
    """2027 is not a leap year. Dropping these people from the list
    entirely would be the silent kind of wrong."""
    make_person("Leap", "Ocampo", born=dt.date(2000, 2, 29))

    entries = upcoming_birthdays(start=dt.date(2027, 2, 20), days=14)

    assert len(entries) == 1
    assert entries[0].day_label == "1 March"


@pytest.mark.django_db
def test_a_29_february_birthday_keeps_its_own_day_in_a_leap_year():
    make_person("Leap", "Ocampo", born=dt.date(2000, 2, 29))

    entries = upcoming_birthdays(start=dt.date(2028, 2, 20), days=14)

    assert entries[0].day_label == "29 February"


@pytest.mark.django_db
def test_a_person_with_no_birthdate_cannot_appear():
    make_person("Blank", "Torres", born=None)

    assert upcoming_birthdays(start=dt.date(2026, 6, 1), days=365) == []


# -- exclusions (spec 7.1) ----------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kwargs",
    [
        {"membership_status": MembershipStatus.DECEASED},
        {"membership_status": MembershipStatus.TRANSFERRED},
        {"date_of_death": dt.date(2026, 1, 1)},
        {"greeting_opt_out": True},
    ],
    ids=["deceased", "transferred", "date_of_death", "opted_out"],
)
def test_each_exclusion_keeps_a_person_off_the_birthday_list(kwargs):
    start = dt.date(2026, 6, 1)
    make_person("Excluded", "Villar", born=dt.date(1990, 6, 10), **kwargs)
    make_person("Included", "Villar", born=dt.date(1990, 6, 10))

    names = [entry.names for entry in upcoming_birthdays(start=start, days=30)]

    assert names == ["Included"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kwargs",
    [
        {"membership_status": MembershipStatus.DECEASED},
        {"date_of_death": dt.date(2026, 1, 1)},
        {"greeting_opt_out": True},
    ],
    ids=["deceased", "date_of_death", "opted_out"],
)
def test_an_anniversary_is_dropped_when_either_spouse_is_excluded(kwargs):
    """Greeting a widow on her wedding anniversary is exactly the error
    that is embarrassing once and preventable permanently."""
    start = dt.date(2026, 6, 1)
    make_couple("Bautista", dt.date(2010, 6, 10), spouse_kwargs=kwargs)

    assert upcoming_anniversaries(start=start, days=30) == []


@pytest.mark.django_db
def test_a_child_opting_out_does_not_suppress_the_parents_anniversary():
    """The exclusion is scoped to the couple, not to everyone under the
    roof -- a teenager who wants no greetings of their own must not erase
    their parents' anniversary."""
    start = dt.date(2026, 6, 1)
    household = make_couple("Gomez", dt.date(2010, 6, 10))
    child = make_person(
        "Kid", "Gomez", born=dt.date(2012, 3, 3), greeting_opt_out=True
    )
    HouseholdMember.objects.create(
        household=household, person=child, role=HouseholdRole.CHILD
    )

    assert len(upcoming_anniversaries(start=start, days=30)) == 1


# -- anniversaries ------------------------------------------------------


@pytest.mark.django_db
def test_an_anniversary_names_both_spouses():
    start = dt.date(2026, 6, 1)
    make_couple(
        "Dizon",
        dt.date(2010, 6, 10),
        head_kwargs={"nickname": "Nonoy"},
        spouse_kwargs={"nickname": "Baby"},
    )

    entry = upcoming_anniversaries(start=start, days=30)[0]

    assert entry.names == "Nonoy and Baby"
    assert entry.day_label == "10 June"


@pytest.mark.django_db
def test_a_household_whose_spouse_never_submitted_a_form_still_gets_an_anniversary():
    """The R33 case: date_of_marriage lives on the household, so a married
    member whose spouse is not in the register still has one from the paper."""
    start = dt.date(2026, 6, 1)
    make_couple("Domingo", dt.date(2010, 6, 10), with_spouse=False)

    entry = upcoming_anniversaries(start=start, days=30)[0]

    assert entry.names == "Head"


@pytest.mark.django_db
def test_a_household_with_no_marriage_date_is_not_an_anniversary():
    household = Household.objects.create(name="Reyes Family")
    person = make_person("Solo", "Reyes")
    HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )

    assert upcoming_anniversaries(start=dt.date(2026, 6, 1), days=365) == []


# -- names and greetings ------------------------------------------------


@pytest.mark.django_db
def test_the_nickname_is_used_when_there_is_one_and_the_first_name_otherwise():
    start = dt.date(2026, 6, 1)
    make_person("Katherine", "Uy", born=dt.date(1990, 6, 2), nickname="Kate")
    make_person("Rodolfo", "Uy", born=dt.date(1990, 6, 3))

    entries = upcoming_birthdays(start=start, days=30)

    assert [entry.names for entry in entries] == ["Kate", "Rodolfo"]
    assert entries[0].subtitle == "Katherine Uy"


@pytest.mark.django_db
def test_a_greeting_is_composed_for_pasting_into_the_church_page():
    start = dt.date(2026, 6, 1)
    make_person("Katherine", "Uy", born=dt.date(1990, 6, 2), nickname="Kate")

    entry = upcoming_birthdays(start=start, days=30)[0]

    assert entry.greeting == BIRTHDAY_GREETING.format(names="Kate")
    assert "Kate" in entry.greeting


@pytest.mark.django_db
def test_one_greeting_covers_everyone_in_the_window():
    """How a church actually posts: one message naming everyone, not three
    separate ones."""
    start = dt.date(2026, 6, 1)
    for index, name in enumerate(["Ana", "Ben", "Carla"]):
        make_person(name, "Santos", born=dt.date(1990, 6, 2 + index))

    text = combined_birthday_greeting(upcoming_birthdays(start=start, days=30))

    assert text == BIRTHDAY_GREETING.format(names="Ana, Ben and Carla")


@pytest.mark.django_db
def test_a_combined_greeting_for_one_person_reads_naturally():
    start = dt.date(2026, 6, 1)
    make_person("Ana", "Santos", born=dt.date(1990, 6, 2))

    assert combined_birthday_greeting(
        upcoming_birthdays(start=start, days=30)
    ) == BIRTHDAY_GREETING.format(names="Ana")


@pytest.mark.django_db
def test_a_combined_greeting_over_nothing_is_empty_rather_than_a_stray_sentence():
    assert combined_birthday_greeting([]) == ""
    assert combined_anniversary_greeting([]) == ""


@pytest.mark.django_db
def test_combined_anniversary_greeting_keeps_couples_apart():
    start = dt.date(2026, 6, 1)
    make_couple(
        "Dizon",
        dt.date(2010, 6, 10),
        head_kwargs={"nickname": "Nonoy"},
        spouse_kwargs={"nickname": "Baby"},
    )
    make_couple(
        "Ramos",
        dt.date(2011, 6, 12),
        head_kwargs={"nickname": "Ping"},
        spouse_kwargs={"nickname": "Let"},
    )

    text = combined_anniversary_greeting(upcoming_anniversaries(start=start, days=30))

    assert text == ANNIVERSARY_GREETING.format(names="Nonoy and Baby, Ping and Let")


# -- the follow-up argument (spec 7.1) ----------------------------------


@pytest.mark.django_db
def test_missing_birthdates_are_counted_so_the_gap_is_visible():
    make_person("Has", "Aquino", born=dt.date(1990, 6, 2))
    make_person("Missing", "Aquino")
    make_person("Also", "Aquino")

    assert missing_birthdate_count() == 2


@pytest.mark.django_db
def test_someone_who_could_never_be_greeted_is_not_counted_as_a_gap():
    """Chasing a transferred member for their birthdate serves nothing --
    they would be excluded from the list even once it arrived."""
    make_person("Gone", "Aquino", membership_status=MembershipStatus.TRANSFERRED)
    make_person("Opted", "Aquino", greeting_opt_out=True)
    make_person("Real", "Aquino")

    assert missing_birthdate_count() == 1
