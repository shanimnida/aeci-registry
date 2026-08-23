"""The church's age bands, decided by the Board and recorded 2026-08-24.

    children  0–12
    juniors   13–15
    youths    16–30

These are the Board's numbers, not a scheme invented here. They matter
because the Board also decided what follows from them: children belong to
the Children's Ministry, and juniors and youths both belong to the Youth
committee, with juniors still marked as juniors.

Nobody above 30 is in a band. That is not an oversight — the Board named
three bands and AEGIS does not invent a fourth by calling everyone else
"adults" and then quietly acting on it.

An age band is computed, never stored. A stored one is wrong the morning
after someone's birthday, and a nightly job to fix that is a job that can
fail silently. The cost is that a band cannot be filtered in the database
the way `Person.has_missing_data` deliberately can (spec 6.3); if a
filtered list view ever needs one, that is the moment to revisit it, not
before.
"""

import datetime as dt

from django.db import models
from django.utils import timezone


class AgeBand(models.TextChoices):
    CHILD = "CHILD", "Child"
    JUNIOR = "JUNIOR", "Junior"
    YOUTH = "YOUTH", "Youth"


# (band, lowest age, highest age). Inclusive at both ends.
BAND_RANGES = (
    (AgeBand.CHILD, 0, 12),
    (AgeBand.JUNIOR, 13, 15),
    (AgeBand.YOUTH, 16, 30),
)

# What each band's age carries with it, as committee codes. The Board's
# rule: "juniors are members of the youth, but still mark them as juniors",
# and youths are on the Youth committee too.
BAND_COMMITTEE_CODES = {
    AgeBand.CHILD: "childrens-ministry",
    AgeBand.JUNIOR: "youth",
    AgeBand.YOUTH: "youth",
}

# The Youth sub-team a junior is placed in, so "still mark them as juniors"
# is visible on the roster without inventing a role for an age band.
JUNIOR_FUNCTION_NAME = "Juniors"


def age_on(date_of_birth, on=None):
    """Whole years old on `on`, or None when there is no birthdate.

    Half the register has no birthdate (spec 7.1), and the seeded officers
    have none by construction, so None is the ordinary case rather than an
    error.
    """
    if date_of_birth is None:
        return None
    on = on or timezone.localdate()
    if date_of_birth > on:
        return None
    had_birthday = (on.month, on.day) >= (date_of_birth.month, date_of_birth.day)
    return on.year - date_of_birth.year - (0 if had_birthday else 1)


def band_for(date_of_birth, on=None):
    """The Board's band for this birthdate, or None.

    None means one of two different things — no birthdate on file, or over
    30 — and the caller should not care which. Both mean "no band applies",
    and neither is a state AEGIS acts on.
    """
    age = age_on(date_of_birth, on)
    if age is None:
        return None
    for band, lowest, highest in BAND_RANGES:
        if lowest <= age <= highest:
            return band
    return None


def band_bounds(band):
    """The (earliest, latest) birthdate that falls in `band` today.

    Lets a derived roster be a single database query instead of a scan over
    every person: someone is a junior today exactly when their birthday
    falls between these two dates. Returns dates, so the comparison happens
    in SQL and the answer changes on its own every midnight.
    """
    on = timezone.localdate()
    for candidate, lowest, highest in BAND_RANGES:
        if candidate != band:
            continue
        # Oldest person still in the band turned `highest` within the last
        # year; youngest turned `lowest` at some point up to today.
        earliest = _shift_years(on, -(highest + 1)) + dt.timedelta(days=1)
        latest = _shift_years(on, -lowest)
        return earliest, latest
    raise ValueError(f"{band!r} is not one of the church's age bands.")


def _shift_years(day, years):
    """`day` moved by `years`, landing on 28 February when the target year
    has no 29th."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)
