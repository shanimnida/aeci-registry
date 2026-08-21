"""Turns reviewer-approved import data into real register rows.

Every object built here is full_clean()-ed before it is saved, and the
whole thing runs inside one transaction. If any piece is refused -- an
impossible date, a second chairperson -- nothing written by this call
survives: the caller catches the ValidationError, shows it against that
person, and the row stays pending. This is the one non-admin write path
the church's hard committee rule (one chairperson per committee) has to be
enforced against, since that rule lives in CommitteeMembership.clean() and
nowhere else. The self-selected committee cap ("select up to TWO (2)") is
no longer one of these refusals -- since 2026-08-17 it is a soft warning
computed by committee_cap_warning, below, shown on the review screen
before the reviewer approves. See
CommitteeMembership.self_selected_overflow_count for why.

CRITICAL 1 (2026-08-16 import fixes): the Member Profiling Form is filled in
once per adult, and both parents' forms list the same children -- that is
how the paper form works. Approving the husband's row and then the wife's
row used to build a brand-new Person for each entry in `children`
unconditionally, and never linked the two households together at all
(HouseholdRole.SPOUSE was never assigned anywhere), so two real children
became four Person rows split across two disconnected households. Fixed by
looking for an existing match -- a child by name *and* date of birth, a
spouse by the free-text `spouse_name` -- before creating anything, and by
reusing whichever household the matched person already belongs to. See
_find_child_match, _find_spouse_match, and the "linked" notices below.

BUG (2026-08-22, empty households): a Household used to be created
unconditionally for every approved row, even a single member with no
spouse, no children and no marriage date -- one person is not a family,
and importing thirty solo forms manufactured thirty households, almost
all of them containing exactly one person. A household is now only
created when the row actually names one: a spouse (named or matched),
at least one child, or a date of marriage (Household.date_of_marriage
has no home on Person, so a marriage date with no linked spouse form
still needs somewhere to live). See _ensure_household, which creates the
household -- and the HEAD membership, and the matched spouse's membership
-- at the first point something in this row actually needs one, instead
of up front. people/management/commands/remove_empty_households.py
cleans up the households this bug already wrote to production.
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person

from .parsing import SELF_SELECTABLE_COMMITTEE_NAMES


def _split_child_name(full_name: str, parent_last_name: str) -> tuple[str, str]:
    """Best-effort split of a one-string full name into (first, last).

    docs/IMPORT_TEMPLATE.md's `children` entries carry only `full_name` --
    there is no separate surname field to transcribe, because the paper form
    itself only has one blank per child. If the name ends with the parent's
    own last name (the common case), that becomes the child's last name and
    the rest is first/middle name. Otherwise the last word is treated as the
    surname. Either way this is a guess: the reviewer sees it as an editable
    field before approving and can correct it.

    Also reused by _find_spouse_match below to pull a first name out of
    `spouse_name`, which is written in the same "FIRST M. LAST" shape.
    """
    full_name = " ".join(full_name.split())
    lowered = full_name.lower()
    parent_last = parent_last_name.strip()
    if parent_last and lowered.endswith(parent_last.lower()):
        remainder = full_name[: -len(parent_last)].strip()
        if remainder:
            return remainder, parent_last
        return full_name, parent_last
    parts = full_name.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return full_name, parent_last or full_name


def _blank_to_none(value):
    return value or None


def _find_child_match(first_name: str, last_name: str, date_of_birth):
    """Look for an existing Person matching a child entry on name AND date of
    birth (CRITICAL 1). Both parents' forms list the same children --
    approving the second parent must reuse the child the first parent's
    approval already created, not build a second one.

    Returns (person_or_None, ambiguous). `ambiguous` is True whenever a
    same-name candidate exists but the match cannot be narrowed to exactly
    one: more than one candidate shares the given date of birth, every
    same-name candidate has a *different* date of birth, or this child's own
    date of birth is missing so nothing could be compared at all. The
    caller must not guess in that case -- it raises a ValidationError and
    lets the reviewer resolve it by correcting the child's name or date of
    birth (or the existing record's), the same way every other
    approval-time refusal in this module works.
    """
    candidates = Person.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name)
    if not candidates.exists():
        return None, False
    if date_of_birth is not None:
        exact = list(candidates.filter(date_of_birth=date_of_birth))
        if len(exact) == 1:
            return exact[0], False
    return None, True


def _find_spouse_match(spouse_name: str, household_surname: str, exclude_pk):
    """A best-effort match of the JSON's free-text `spouse_name` against an
    existing Person (CRITICAL 1). There is no link, only a name someone
    handwrote on a form -- _split_child_name's same surname-stripping guess
    is reused to pull out a first name to compare, since spouse_name carries
    the same "FIRST M. LAST" shape a child's full_name does.

    Returns (person_or_None, ambiguous). Unlike a child match, an ambiguous
    spouse match does not block approval -- linking a spouse is a
    convenience, not something the rest of the row's correctness depends on
    -- so the caller treats it as "no match" and tells the reviewer why, in
    case a same-named stranger almost got linked by mistake.
    """
    spouse_name = " ".join((spouse_name or "").split())
    if not spouse_name:
        return None, False
    _, guessed_last = _split_child_name(spouse_name, household_surname)
    normalized = spouse_name.lower()
    candidates = Person.objects.filter(last_name__iexact=guessed_last).exclude(pk=exclude_pk)
    matches = [
        candidate
        for candidate in candidates
        if candidate.first_name.strip() and normalized.startswith(candidate.first_name.strip().lower())
    ]
    if len(matches) == 1:
        return matches[0], False
    if matches:
        return None, True
    return None, False


def _reconcile_marriage_date(household, date_of_marriage, user, notices):
    """Carry this row's date of marriage onto a household that already
    existed (BUG, 2026-08-22: empty households).

    `date_of_marriage` lives on Household and has no home on Person, so a
    row whose spouse was matched to someone who already has a household --
    the CRITICAL 1 reuse path above -- used to drop the date on the floor
    whenever the spouse's own form had not carried one. Both halves of a
    married couple fill in their own paper form, and only one of them may
    have written the date down.

    Fills the gap only when the household has no date at all. It never
    overwrites one: two forms disagreeing about a wedding date is a
    question for the reviewer holding both sheets of paper, not something
    to resolve by whichever row happened to be approved second, so the
    disagreement is reported and the stored date left alone.
    """
    if date_of_marriage is None:
        return
    # The review form hands every date over as free text (imports/forms.py
    # keeps them CharFields so an unreadable scrawl can still be staged and
    # corrected), so normalise before comparing -- "2012-04-04" and
    # date(2012, 4, 4) are the same wedding, and comparing the two raw
    # would report a disagreement that is not there. A string that is not a
    # date at all raises ValidationError here, which the review screen
    # already knows how to show against this row.
    date_of_marriage = models.DateField().to_python(date_of_marriage)
    if household.date_of_marriage is None:
        household.date_of_marriage = date_of_marriage
        household.updated_by = user
        household.full_clean()
        household.save()
        notices.append(
            f"Recorded this form's date of marriage ({date_of_marriage}) on the existing "
            f"household ({household}), which had none on file."
        )
    elif household.date_of_marriage != date_of_marriage:
        notices.append(
            f"This form gives the date of marriage as {date_of_marriage}, but household "
            f"({household}) already records {household.date_of_marriage}. Kept the recorded "
            "date -- check both paper forms and correct the household by hand if needed."
        )


def _ensure_household(household, person, spouse_match, cleaned, user, notices):
    """Return `household`, creating it first if it is still None (BUG,
    2026-08-22: empty households). Called at each point in
    build_person_from_import where something -- a named spouse, a date of
    marriage, a real child entry -- first actually needs a household to
    exist, rather than one being made up front and possibly left holding
    nobody but `person`. Idempotent: once a household exists, later calls
    just hand it back unchanged, so callers can call this unconditionally
    at every point of potential need without worrying about a second one
    getting created.

    The newly created household always gets `person` as its HEAD, and (if
    `spouse_match` is set -- an existing Person matched by name who is not
    already in a household of their own; see the caller's earlier check)
    `spouse_match` as its SPOUSE, with a notice reported to the reviewer.
    """
    if household is not None:
        return household

    household = Household(
        name=f"{person.last_name} Family",
        address=cleaned.get("home_address") or "",
        date_of_marriage=_blank_to_none(cleaned.get("date_of_marriage")),
        created_by=user,
        updated_by=user,
    )
    household.full_clean()
    household.save()

    head = HouseholdMember(household=household, person=person, role=HouseholdRole.HEAD)
    head.full_clean()
    head.save()

    if spouse_match is not None:
        # Matched by name, but not yet in any household of their own (e.g.
        # added to the register outside this workflow).
        member = HouseholdMember(household=household, person=spouse_match, role=HouseholdRole.SPOUSE)
        member.full_clean()
        member.save()
        notices.append(f"Linked to existing person {spouse_match.full_name} as spouse.")

    return household


def build_person_from_import(cleaned: dict, children: list[dict], user) -> tuple[Person, list[str]]:
    """Create (or link) the Person, Household, child Persons and
    CommitteeMemberships for one approved import row.

    Returns (person, notices). `person` is always a freshly created Person
    for this row -- the primary subject of the paper form being approved is
    always a real, distinct human who filled in their own form, so they are
    never matched against an existing record the way children and spouses
    are. `notices` lists every place this call *linked* to an existing
    record instead of creating one (CRITICAL 1's reporting requirement --
    silent linking is as bad as silent duplication); the caller shows each
    one to the reviewer.

    `cleaned` is the reviewer's (possibly corrected) data for the primary
    person, keyed the same as docs/IMPORT_TEMPLATE.md's JSON shape plus
    `membership_status` (a reviewer decision the AI never makes -- see
    import-feature-report.md). `children` is a list of {full_name,
    date_of_birth} dicts, same shape as the JSON's `children` array.
    """
    notices: list[str] = []
    with transaction.atomic():
        person = Person(
            member_no=_blank_to_none(cleaned.get("member_no")),
            last_name=cleaned["last_name"],
            first_name=cleaned["first_name"],
            middle_name=cleaned.get("middle_name") or "",
            suffix=cleaned.get("suffix") or "",
            date_of_birth=_blank_to_none(cleaned.get("date_of_birth")),
            place_of_birth=cleaned.get("place_of_birth") or "",
            gender=cleaned.get("gender") or "",
            civil_status=cleaned.get("civil_status") or "",
            nationality=cleaned.get("nationality") or "Filipino",
            home_address=cleaned.get("home_address") or "",
            mobile_number=cleaned.get("mobile_number") or "",
            email=cleaned.get("email") or "",
            membership_status=cleaned.get("membership_status") or MembershipStatus.MEMBER,
            date_filed=_blank_to_none(cleaned.get("date_filed")),
            emergency_contact_name=cleaned.get("emergency_contact_name") or "",
            emergency_contact_relationship=cleaned.get("emergency_relationship") or "",
            emergency_contact_number=cleaned.get("emergency_number") or "",
            notes=cleaned.get("notes") or "",
            created_by=user,
            updated_by=user,
        )
        # form_version decides whether a Data Privacy Consent section existed
        # on the paper form at all (docs/IMPORT_TEMPLATE.md) -- v1 forms never
        # asked, so there is nothing to record as consent for them.
        if cleaned.get("form_version") == "v2":
            person.consent_given = True
            person.consent_date = _blank_to_none(cleaned.get("certification_date"))
            person.consent_version = "v2"
        person.full_clean()
        person.save()

        # -- spouse + household (CRITICAL 1) --------------------------------
        spouse_name = (cleaned.get("spouse_name") or "").strip()
        spouse_match = None
        if spouse_name:
            spouse_match, spouse_ambiguous = _find_spouse_match(spouse_name, person.last_name, person.pk)
            if spouse_ambiguous:
                notices.append(
                    f"'{spouse_name}' (spouse) matches more than one existing person -- not "
                    "linked automatically. Link the household by hand if one of them is the "
                    "same person."
                )
                spouse_match = None

        date_of_marriage = _blank_to_none(cleaned.get("date_of_marriage"))

        household = None
        if spouse_match is not None:
            spouse_membership = (
                HouseholdMember.objects.filter(person=spouse_match).select_related("household").first()
            )
            if spouse_membership is not None:
                # The spouse's own form was approved first and already has a
                # household -- reuse it instead of starting a second one that
                # would leave the two forms split apart (CRITICAL 1).
                household = spouse_membership.household
                if not HouseholdMember.objects.filter(household=household, person=person).exists():
                    member = HouseholdMember(household=household, person=person, role=HouseholdRole.SPOUSE)
                    member.full_clean()
                    member.save()
                notices.append(
                    f"Linked to {spouse_match.full_name}'s existing household "
                    f"({household}) as spouse, rather than starting a new one."
                )
                _reconcile_marriage_date(household, date_of_marriage, user, notices)

        # A household is worth creating even before any child is seen when
        # the row itself names a family on its own: a spouse (named, even if
        # not matched to anyone -- see _find_spouse_match's ambiguous case),
        # or a date of marriage, which has nowhere to live but
        # Household.date_of_marriage (BUG, 2026-08-22: empty households).
        # `spouse_match` can only be set when `spouse_name` is (see
        # _find_spouse_match), so this also covers the matched-spouse case.
        if household is None and (spouse_name or date_of_marriage):
            household = _ensure_household(household, person, spouse_match, cleaned, user, notices)

        # -- children (CRITICAL 1) -------------------------------------------
        for child in children:
            full_name = (child.get("full_name") or "").strip()
            if not full_name:
                continue
            # A real child entry is itself reason enough for a household,
            # even for a row with no spouse and no marriage date on file
            # (BUG, 2026-08-22: empty households) -- created here, the first
            # point a household is actually needed, if nothing earlier
            # already made one.
            household = _ensure_household(household, person, spouse_match, cleaned, user, notices)
            first_name, last_name = _split_child_name(full_name, person.last_name)
            date_of_birth = _blank_to_none(child.get("date_of_birth"))

            match, ambiguous = _find_child_match(first_name, last_name, date_of_birth)
            if ambiguous:
                raise ValidationError(
                    f"'{full_name}' matches more than one existing person, or an existing "
                    "person of that name with a different or missing date of birth -- AEGIS "
                    "will not guess which one this is. Correct the child's name or date of "
                    "birth (or the existing record's) before approving."
                )

            if match is not None:
                child_person = match
                notices.append(f"Linked to existing child {child_person.full_name}.")
            else:
                child_person = Person(
                    last_name=last_name,
                    first_name=first_name,
                    date_of_birth=date_of_birth,
                    membership_status=MembershipStatus.CHILD,
                    guardian=person,
                    nationality=person.nationality,
                    created_by=user,
                    updated_by=user,
                )
                child_person.full_clean()
                child_person.save()

            if not HouseholdMember.objects.filter(household=household, person=child_person).exists():
                child_membership = HouseholdMember(
                    household=household, person=child_person, role=HouseholdRole.CHILD
                )
                child_membership.full_clean()
                child_membership.save()

        committee_names = cleaned.get("committees") or []
        joined_on = (
            _blank_to_none(cleaned.get("date_filed"))
            or _blank_to_none(cleaned.get("certification_date"))
            or timezone.localdate()
        )
        for committee_name in committee_names:
            committee = Committee.objects.filter(name=committee_name).first()
            if committee is None:
                raise ValidationError(
                    f"'{committee_name}' does not match any known committee."
                )
            membership = CommitteeMembership(
                committee=committee,
                person=person,
                role=CommitteeRole.MEMBER,
                date_joined=joined_on,
                created_by=user,
                updated_by=user,
            )
            membership.full_clean()
            membership.save()

        return person, notices


def _describe_duplicate_match(candidate, date_of_birth):
    """Mirrors people.admin.describe_duplicate_match -- see there for the
    full reasoning. Kept as a separate copy rather than an import because
    this module works from a staged row's raw dict, not a Person, and the
    two admin apps' write paths are already kept independent of each other
    (see this module's own docstring and possible_duplicate_warning below).
    """
    if date_of_birth and candidate.date_of_birth:
        return f"{candidate} (same name and birthdate)"
    if date_of_birth and not candidate.date_of_birth:
        return f"{candidate} (same name; existing record has no birthdate on file)"
    return f"{candidate} (name match only)"


def possible_duplicate_warning(data: dict) -> str | None:
    """Mirrors people.admin.PersonAdmin.save_model's soft duplicate warning,
    computed from a staged row's own field values rather than a saved
    Person -- so the reviewer sees it on the review screen before approving
    (MINOR 8), not as a flash message after the Person already exists.
    Never blocks: two people genuinely can share a name.

    Same NULL-blindness fix as people.admin.find_possible_duplicates: an
    absent date of birth on the *existing* record is not evidence it is a
    different person (see that function's docstring for the seeded-officer
    case this exists for), so when the staged row carries a birthdate, a
    same-name existing record with no birthdate on file still counts as a
    match, not just one with the identical date.
    """
    last_name = (data.get("last_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    if not last_name or not first_name:
        return None
    matches = Person.objects.filter(last_name__iexact=last_name, first_name__iexact=first_name)
    date_of_birth = data.get("date_of_birth")
    if date_of_birth:
        matches = matches.filter(Q(date_of_birth=date_of_birth) | Q(date_of_birth__isnull=True))
    if not matches.exists():
        return None
    descriptions = ", ".join(
        _describe_duplicate_match(candidate, date_of_birth) for candidate in matches[:3]
    )
    return f"This may duplicate an existing record: {descriptions}. Check before approving."


def committee_cap_warning(data: dict) -> str | None:
    """Mirrors possible_duplicate_warning above: a soft warning computed from
    a staged row's own field values, so the reviewer sees it on the review
    screen before approving, rather than after -- the same reasoning MINOR 8
    used for the duplicate warning.

    This person is always brand new (build_person_from_import never matches
    the row's primary subject against an existing Person), so the ticked
    `committees` list on this row *is* the person's whole self-selected
    count -- no need to query existing memberships the way
    CommitteeMembership.self_selected_overflow_count does for the general
    case. `Grievance and Reconciliation` is excluded from the count: it is
    not self-selectable (docs/IMPORT_TEMPLATE.md), so a stray tick of it
    does not use up one of the form's two self-selected slots.

    Never blocks: the cap is church policy printed on the form, not a
    structural fact about the data, and the church has already accepted
    real forms (four of the first thirty collected) that ticked more than
    two. See CommitteeMembership.self_selected_overflow_count for the full
    reasoning.
    """
    committees = [
        name for name in (data.get("committees") or []) if name in SELF_SELECTABLE_COMMITTEE_NAMES
    ]
    limit = CommitteeMembership.SELF_SELECTED_LIMIT
    if len(committees) <= limit:
        return None
    return (
        f"This person ticked {len(committees)} committees. The profiling form asks "
        f"for up to {limit}. Check this reflects the paper before approving."
    )
