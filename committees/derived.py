"""Committee places that follow from a person's age, not from a decision.

The Board's rule, recorded 2026-08-24: children (0–12) belong to the
Children's Ministry, and juniors (13–15) and youths (16–30) belong to the
Youth committee, with juniors still marked as juniors.

**Nothing here writes a row.** A derived place is computed every time it is
asked for, so somebody joins the Youth committee on their thirteenth
birthday and leaves it the day after their thirty-first without a job
running, a migration, or a membership row appearing and disappearing under
a name nobody typed. That was the choice made deliberately over creating
real memberships: an automatic row has to be automatically ended, and the
ending is the part that goes wrong quietly.

The cost, stated plainly: a derived place is not a `CommitteeMembership`,
so it does not appear in the membership changelist, does not carry a
`date_joined`, and cannot hold a role other than the one its band implies.
Anyone who needs one of those things gets a real membership recorded by
hand — which the roster shows alongside, and which always wins.

People with no birthdate on file are simply not placed. They can be added
to any committee by hand, exactly as before; the age rule only ever adds.
"""

from dataclasses import dataclass

from django.db.models import Q

from committees.models import Committee, CommitteeRole
from people.agebands import (
    BAND_COMMITTEE_CODES,
    JUNIOR_FUNCTION_NAME,
    AgeBand,
    band_bounds,
)
from people.models import MembershipStatus, Person

# Somebody the church has stopped counting is not swept back onto a roster
# by their birthday.
EXCLUDED_STATUSES = (MembershipStatus.TRANSFERRED, MembershipStatus.DECEASED)


@dataclass(frozen=True)
class DerivedPlace:
    """A stand-in for a CommitteeMembership that was never recorded.

    Carries the same three attributes the roster templates read off a real
    membership -- person, role, function name -- plus `band`, so a junior
    can be marked as one, and `is_derived`, so the roster can say plainly
    that this place follows from an age rather than from a decision.
    """

    person: Person
    band: str
    function_name: str = ""
    role: str = CommitteeRole.MEMBER
    is_derived: bool = True

    def get_role_display(self):
        return "Member"


def _band_people(band):
    earliest, latest = band_bounds(band)
    return (
        Person.objects.filter(date_of_birth__range=(earliest, latest))
        .exclude(membership_status__in=EXCLUDED_STATUSES)
        .filter(date_of_death__isnull=True)
        .order_by("last_name", "first_name")
    )


def bands_for_committee(committee_code) -> list:
    return [
        band for band, code in BAND_COMMITTEE_CODES.items() if code == committee_code
    ]


def derived_places(committee, exclude_person_ids=()) -> list:
    """Everyone whose age puts them on `committee` today.

    `exclude_person_ids` is how a real membership wins: a person already
    recorded on this committee -- as its chairperson, or as an ordinary
    member somebody typed in -- is left out here so they appear once, with
    the role they were actually given.
    """
    bands = bands_for_committee(committee.code)
    if not bands:
        return []

    places = []
    for band in bands:
        function_name = JUNIOR_FUNCTION_NAME if band == AgeBand.JUNIOR else ""
        for person in _band_people(band):
            if person.pk in exclude_person_ids:
                continue
            places.append(
                DerivedPlace(person=person, band=band, function_name=function_name)
            )
    places.sort(key=lambda place: (place.person.last_name, place.person.first_name))
    return places


def derived_committee_codes() -> set:
    return set(BAND_COMMITTEE_CODES.values())


def unplaceable_count() -> int:
    """How many people cannot be placed because they have no birthdate.

    Shown on the rosters that use the age rule, for the same reason the
    Celebrations page shows it (spec 7.1): the absence is a task, and a
    roster that silently omits nine people is worse than one that says so.
    """
    return (
        Person.objects.filter(date_of_birth__isnull=True)
        .exclude(membership_status__in=EXCLUDED_STATUSES)
        .filter(date_of_death__isnull=True)
        .count()
    )
