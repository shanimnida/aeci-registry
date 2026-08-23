"""Upcoming birthdays and wedding anniversaries (spec 7.1).

The Church Secretary's original reason for asking for AEGIS. Kept as plain
callables with no request and no HTTP so the date logic -- which has more
edge cases than it looks like it does -- can be read and tested on its own;
PersonAdmin.celebrations_view renders what these return.

Two rules from the spec shape everything here:

- **Month and day only, never the year (D17).** A birth year reveals an age
  to people who have no need for it, so `Celebration` exposes `day_label`
  ("14 October") and nothing a template could accidentally render a year
  from. `date` is the occurrence used for sorting; it is not for display.
- **The exclusions are not decoration.** Anyone DECEASED or TRANSFERRED,
  anyone with `date_of_death` set, and anyone who opted out never appears.
  A deceased member on a birthday list is the kind of error that is
  embarrassing once and preventable permanently, and the anniversary half
  is worse -- see `upcoming_anniversaries`.
"""

import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from committees.models import CommitteeMembership, CommitteeRole
from core import groups
from people.models import Household, HouseholdRole, MembershipStatus, Person

DEFAULT_WINDOW_DAYS = 30
DASHBOARD_WINDOW_DAYS = 7

# Rolling rather than calendar-month on purpose: on the 29th, a calendar
# month would show almost nothing while three people have birthdays that
# week.

# The wording the church sends out. A module constant rather than a
# settings field or a database row because nobody has asked to edit it yet;
# when someone does, this is one string to move. English throughout, as the
# forms and the church's own Facebook page are.
BIRTHDAY_GREETING = (
    "Happy birthday, {names}! From your church family at Avdei Elohim Church Inc."
)
ANNIVERSARY_GREETING = (
    "Happy wedding anniversary, {names}! "
    "From your church family at Avdei Elohim Church Inc."
)

# Spec 7.1's exclusions, as a status list. `date_of_death` and
# `greeting_opt_out` are separate fields and handled alongside it.
UNGREETABLE_STATUSES = (MembershipStatus.DECEASED, MembershipStatus.TRANSFERRED)

# Spec 7.7 names the Sunshine Committee's chairperson as the one chairperson
# who sees this report -- Sunshine handles greetings and benevolence, so it
# is the natural owner alongside the Secretariat.
SUNSHINE_COMMITTEE_CODE = "sunshine"
SUNSHINE_LEAD_ROLES = (CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR)


@dataclass(frozen=True)
class Celebration:
    """One line on the page.

    `names` is who to greet, nickname-first, and is what goes into the
    message. `subtitle` is the full legal name, so the Secretariat can tell
    two Anas apart. `date` sorts; it is never rendered -- see D17 above.
    """

    date: dt.date
    day_label: str
    names: str
    subtitle: str
    greeting: str


def _display_name(person) -> str:
    """The name a person actually goes by (spec 3.2 on `nickname`)."""
    return (person.nickname or "").strip() or person.first_name


def _join_names(names) -> str:
    names = [name for name in names if name]
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _day_label(day: dt.date) -> str:
    """"14 October" -- built by hand rather than with strftime because
    %-d is not portable to Windows, where this is developed."""
    return f"{day.day} {day.strftime('%B')}"


def _occurrence(day: dt.date, year: int) -> dt.date:
    """The date `day`'s month and day falls on in `year`.

    29 February has no counterpart in a common year. Those people are
    greeted on 1 March instead of being dropped from the list, which would
    be the silent kind of wrong -- and 1 March is the day the church would
    actually greet them, so it is also what the label should say.
    """
    try:
        return day.replace(year=year)
    except ValueError:
        return dt.date(year, 3, 1)


def _in_window(day: dt.date, start: dt.date, days: int):
    """The occurrence of `day` inside [start, start + days], or None.

    Both years are tried so a window opened in December reaches into
    January. Endpoints are inclusive: a birthday today is still today's.
    """
    end = start + dt.timedelta(days=days)
    for year in (start.year, start.year + 1):
        occurrence = _occurrence(day, year)
        if start <= occurrence <= end:
            return occurrence
    return None


def _is_greetable(person) -> bool:
    """The spec 7.1 exclusions as a predicate over an in-memory Person.

    Mirrors `greetable_people()` below; the two exist separately because
    anniversaries reach their people through a household's members rather
    than through a queryset over Person.
    """
    return (
        person.membership_status not in UNGREETABLE_STATUSES
        and person.date_of_death is None
        and not person.greeting_opt_out
    )


def greetable_people():
    return (
        Person.objects.exclude(membership_status__in=UNGREETABLE_STATUSES)
        .filter(date_of_death__isnull=True)
        .filter(greeting_opt_out=False)
    )


# The periods the Show buttons offer, requested 2026-08-24. A church works
# to a weekly rhythm (a Sunday service) and plans to a monthly one, so
# "this week" and "this month" are the questions actually being asked --
# "the next 30 days" was an answer to a question nobody phrased that way.
PERIODS = ("week", "month", "next-month")
DEFAULT_PERIOD = "month"


def period_bounds(period, on=None):
    """(first day, last day, label) for one of PERIODS.

    Calendar periods, not rolling ones, and they include days already past.
    That is deliberate: the page answers "has everyone been greeted this
    week", and a Wednesday view that hid Monday's birthday would answer it
    wrongly. The rolling window is still available through `?days=` for
    anyone who wants "the next N days" -- and is what the dashboard panel
    uses, where the question really is "what is coming".
    """
    on = on or timezone.localdate()
    if period == "week":
        # Sunday to Saturday. The Philippine convention, and the week a
        # church actually plans around, since the service anchors it.
        start = on - dt.timedelta(days=(on.weekday() + 1) % 7)
        return start, start + dt.timedelta(days=6), "This week"
    if period == "next-month":
        first = (on.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        return first, _end_of_month(first), first.strftime("%B")
    first = on.replace(day=1)
    return first, _end_of_month(first), "This month"


def _end_of_month(first_of_month):
    following = (first_of_month + dt.timedelta(days=32)).replace(day=1)
    return following - dt.timedelta(days=1)


def _in_range(day, first, last):
    """The occurrence of `day` between `first` and `last`, or None.

    Both years are tried so a period spanning the year end still matches,
    which "next month" does every December.
    """
    for year in (first.year, last.year):
        occurrence = _occurrence(day, year)
        if first <= occurrence <= last:
            return occurrence
    return None


def celebrations_for_period(period, on=None):
    """Birthdays and anniversaries in a calendar period, as one call."""
    first, last, label = period_bounds(period, on)
    return (
        birthdays_between(first, last),
        anniversaries_between(first, last),
        label,
    )


def birthdays_between(first, last) -> list[Celebration]:
    entries = []
    for person in greetable_people().filter(date_of_birth__isnull=False):
        occurrence = _in_range(person.date_of_birth, first, last)
        if occurrence is None:
            continue
        names = _display_name(person)
        entries.append(
            Celebration(
                date=occurrence,
                day_label=_day_label(occurrence),
                names=names,
                subtitle=person.full_name,
                greeting=BIRTHDAY_GREETING.format(names=names),
            )
        )
    return sorted(entries, key=lambda entry: (entry.date, entry.subtitle))


def anniversaries_between(first, last) -> list[Celebration]:
    """Wedding anniversaries, from `Household.date_of_marriage`.

    The couple is the household's HEAD and SPOUSE rows, and the exclusions
    are applied to *them* rather than to everyone under the roof: a
    teenager who wants no greetings of their own must not erase their
    parents' anniversary, but greeting a widow on hers is precisely the
    error the exclusions exist to prevent, so one excluded spouse drops the
    whole entry.

    A household with a HEAD and no SPOUSE still counts. `date_of_marriage`
    lives on the household and has no home on Person, so a married member
    whose spouse never submitted their own form still has the date from the
    paper -- see the R33 fix in imports/services.py.
    """
    households = Household.objects.filter(
        date_of_marriage__isnull=False
    ).prefetch_related("members__person")

    entries = []
    for household in households:
        occurrence = _in_range(household.date_of_marriage, first, last)
        if occurrence is None:
            continue
        couple = [
            member
            for member in household.members.all()
            if member.role in (HouseholdRole.HEAD, HouseholdRole.SPOUSE)
        ]
        if not couple:
            continue
        if not all(_is_greetable(member.person) for member in couple):
            continue
        # HEAD before SPOUSE, so the greeting reads the same way twice.
        couple.sort(key=lambda member: 0 if member.role == HouseholdRole.HEAD else 1)
        names = _join_names([_display_name(member.person) for member in couple])
        entries.append(
            Celebration(
                date=occurrence,
                day_label=_day_label(occurrence),
                names=names,
                subtitle=household.name,
                greeting=ANNIVERSARY_GREETING.format(names=names),
            )
        )
    return sorted(entries, key=lambda entry: (entry.date, entry.subtitle))


def upcoming_birthdays(start=None, days=DEFAULT_WINDOW_DAYS) -> list[Celebration]:
    """The rolling window, still used by the dashboard panel where the
    question really is "what is coming" rather than "this month"."""
    start = start or timezone.localdate()
    return birthdays_between(start, start + dt.timedelta(days=days))


def upcoming_anniversaries(start=None, days=DEFAULT_WINDOW_DAYS) -> list[Celebration]:
    start = start or timezone.localdate()
    return anniversaries_between(start, start + dt.timedelta(days=days))


def combined_birthday_greeting(entries) -> str:
    """One message naming everyone in the window, which is how a church
    actually posts -- not one message per person."""
    names = _join_names([entry.names for entry in entries])
    return BIRTHDAY_GREETING.format(names=names) if names else ""


def combined_anniversary_greeting(entries) -> str:
    """As above, but couples are already joined with "and" inside each
    entry, so a second "and" between them would read as one long list of
    individuals rather than as several couples."""
    names = ", ".join(entry.names for entry in entries if entry.names)
    return ANNIVERSARY_GREETING.format(names=names) if names else ""


def missing_birthdate_count() -> int:
    """How many greetable people have no birthdate on file.

    Spec 7.1: those people cannot appear on this page at all, which makes
    the celebrations screen "a standing, visible argument for working the
    follow-up queue". Counted over greetable people only -- chasing a
    transferred member for their birthdate serves nothing, since they would
    still be excluded once it arrived.
    """
    return greetable_people().filter(date_of_birth__isnull=True).count()


def may_view_celebrations(user) -> bool:
    """Spec 7.7: Secretariat, ICT, and the Sunshine chairperson.

    Deliberately wider than D12 for that one chairperson: Sunshine's lead
    sees names and dates for the whole congregation, not just their own
    roster, because greetings are the committee's actual job. Every other
    chairperson is refused. The Board and Treasurer are not on the spec's
    list for this report and are refused too.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    names = set(user.groups.values_list("name", flat=True))
    if names & {groups.ICT, groups.SECRETARIAT}:
        return True
    return (
        CommitteeMembership.objects.active()
        .filter(
            person__user=user,
            committee__code=SUNSHINE_COMMITTEE_CODE,
            role__in=SUNSHINE_LEAD_ROLES,
        )
        .exists()
    )
