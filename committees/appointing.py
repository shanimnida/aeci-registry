"""Who may appoint whom, to what, on which committee.

Requested 2026-08-24: put every appointment in one place, and let a
chairperson appoint their own co-chair and secretary — which is the Board's
own structure (the Board appoints each chairperson; each chairperson
appoints their own vice and secretary).

**This closes the hole that stopped chairpersons managing rosters at all.**
The objection was that appointing somebody means finding them, and a
chairperson cannot see anyone off their own roster (D12) — so an appoint
screen would have needed a person-picker reaching past the scoping. It does
not, because of who a chairperson is allowed to appoint: their co-chair and
secretary come from the people already serving on their committee. They
never need to see anyone they could not already see.

No new model permission is granted to the Chairperson group. The gate lives
here and the view creates the membership itself, so the ordinary "add
committee membership" form stays shut to them — a chairperson who could
reach that form could put anyone on any committee in any role, which is
precisely what this narrowness exists to prevent.
"""

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from core.groups import is_chairperson_only
from people.models import Person

# What the Board and ICT may appoint. Spec 4: "Appoint officers /
# chairpersons — ICT, Board".
BOARD_APPOINTABLE_ROLES = (
    CommitteeRole.CHAIRPERSON,
    CommitteeRole.CO_CHAIR,
    CommitteeRole.SECRETARY,
    CommitteeRole.OVERSIGHT,
)

# Board Oversight is the Board's own seat on a committee, and the church
# named who may fill it (2026-08-24): "board oversight can only be
# appointed by the board, secretary, or superadmin/ICT". The Secretariat is
# on that list and on no other part of this screen -- it records the
# Board's decision without acquiring the power to appoint chairpersons,
# which spec 4 keeps with ICT and the Board.
SECRETARIAT_APPOINTABLE_ROLES = (CommitteeRole.OVERSIGHT,)

# What a chairperson may appoint on a committee they lead. Not CHAIRPERSON:
# a chairperson naming their own successor is the one appointment that is
# not theirs to make.
CHAIRPERSON_APPOINTABLE_ROLES = (
    CommitteeRole.CO_CHAIR,
    CommitteeRole.SECRETARY,
)


def _group_names(user):
    return set(user.groups.values_list("name", flat=True))


def may_appoint(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    names = _group_names(user)
    if names & {groups.ICT, groups.BOARD, groups.SECRETARIAT}:
        return True
    return bool(committees_led_by(user))


def committees_led_by(user):
    """Committees this user chairs or co-chairs, actively.

    Co-chairs count: a co-chair standing in for an absent chairperson who
    cannot appoint a secretary is a co-chair who cannot do the job.
    """
    return Committee.objects.filter(
        pk__in=CommitteeMembership.objects.active()
        .filter(
            person__user=user,
            role__in=(CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR),
        )
        .values_list("committee_id", flat=True)
    ).order_by("name")


def appointable_committees(user):
    """Committees this user may appoint an officer on.

    `has_officers=False` committees are excluded for everybody: an appointed
    body has no chairperson, co-chair or secretary to fill (see
    Committee.has_officers). Its members are recorded on the ordinary
    committee-membership screen, which is what they are -- members.
    """
    if user.is_superuser or _group_names(user) & {
        groups.ICT, groups.BOARD, groups.SECRETARIAT
    }:
        return Committee.objects.filter(is_active=True, has_officers=True).order_by("name")
    return committees_led_by(user).filter(has_officers=True)


def appointable_roles(user):
    if user.is_superuser or _group_names(user) & {groups.ICT, groups.BOARD}:
        return BOARD_APPOINTABLE_ROLES
    if groups.SECRETARIAT in _group_names(user):
        return SECRETARIAT_APPOINTABLE_ROLES
    return CHAIRPERSON_APPOINTABLE_ROLES


def appointable_people(user, committee):
    """Who may be appointed to an office on `committee`.

    For the Board and ICT, anybody — they are choosing an officer for the
    church and are not scoped to a roster.

    For a chairperson, only people already serving on that committee. That
    is what makes this screen reachable by a chairperson at all: they pick
    from the roster they can already see, so no field is disclosed that D12
    withholds, and there is no person-picker reaching past their scoping.
    """
    if user.is_superuser or _group_names(user) & {
        groups.ICT, groups.BOARD, groups.SECRETARIAT
    }:
        return Person.objects.all().order_by("last_name", "first_name")
    return Person.objects.filter(
        pk__in=CommitteeMembership.objects.active()
        .filter(committee=committee)
        .values_list("person_id", flat=True)
    ).order_by("last_name", "first_name")


def may_appoint_on(user, committee) -> bool:
    return appointable_committees(user).filter(pk=committee.pk).exists()


def current_officers(committee):
    """Everyone currently holding an office on `committee`, in rank order."""
    order = {
        CommitteeRole.CHAIRPERSON: 0,
        CommitteeRole.CO_CHAIR: 1,
        CommitteeRole.SECRETARY: 2,
        CommitteeRole.OVERSIGHT: 3,
    }
    officers = list(
        CommitteeMembership.objects.active()
        .filter(committee=committee, role__in=BOARD_APPOINTABLE_ROLES)
        .select_related("person")
    )
    officers.sort(key=lambda membership: order.get(membership.role, 9))
    return officers


def may_end(user, membership) -> bool:
    """Ending an office is scoped the same way appointing it is.

    A chairperson may end their own co-chair or secretary — appointing a
    replacement requires it, since one person holds an office at a time —
    but never their own chairpersonship, and never anyone else's.
    """
    if not may_appoint_on(user, membership.committee):
        return False
    return membership.role in appointable_roles(user)
