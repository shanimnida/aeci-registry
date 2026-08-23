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


def _split_child_name(full_name: str, parent_last_name: str) -> tuple[str, str, str]:
    """Best-effort split of a one-string full name into (first, middle, last).

    docs/IMPORT_TEMPLATE.md's child entries carry only `full_name` -- the
    paper form has one blank per child, not three -- so the parts have to be
    guessed. If the name ends with the parent's own last name (the common
    case) that becomes the surname; otherwise the last word is.

    BUG (2026-08-23, middle names): this used to return only (first, last),
    folding everything else into the first name, so "Rhyzel Bayatin Abaigar"
    was stored as first_name="Rhyzel Bayatin" with a blank middle_name. That
    put the middle name in the wrong field AND made the row unmatchable
    against the same child encoded properly by hand. Of whatever is left
    after the surname, the LAST token is now taken as the middle name --
    the convention the paper form itself follows -- and everything before it
    as the first name, so "Juan Miguel Reyes Delacruz" gives first "Juan
    Miguel", middle "Reyes".

    Still a guess, and still shown to the reviewer as three editable fields
    before anything is approved.

    Also reused by _find_spouse_match below to pull a first name out of
    `spouse_name`, which is written in the same shape.
    """
    full_name = " ".join(full_name.split())
    parent_last = parent_last_name.strip()

    if parent_last and full_name.lower().endswith(parent_last.lower()):
        remainder = full_name[: -len(parent_last)].strip()
        if not remainder:
            # The whole name IS the parent's surname -- nothing to split.
            return full_name, "", parent_last
        last = parent_last
    else:
        parts = full_name.rsplit(" ", 1)
        if len(parts) != 2:
            return full_name, "", parent_last or full_name
        remainder, last = parts

    tokens = remainder.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]), tokens[-1], last
    return remainder, "", last


def _given_name_tokens(first_name: str, middle_name: str) -> list[str]:
    """Every given-name word a person carries, lowercased, however the
    record happens to distribute them between the two fields.

    This is what makes the three storage shapes of one child comparable:
    ("Rhyzel", "Bayatin") encoded by hand, ("Rhyzel Bayatin", "") written by
    the old buggy splitter, and ("Rhyzel", "") from a form that omitted the
    middle name all reduce to a token list that can be compared.
    """
    tokens = []
    for part in (first_name, middle_name):
        tokens.extend((part or "").lower().split())
    return tokens


def _names_are_compatible(incoming: list[str], candidate: list[str]) -> bool:
    """True when two given-name token lists could be the same person.

    They must agree on the first given name, and one must be contained in
    the other. A MISSING middle name is tolerated -- half the paper forms
    leave it out -- but a CONTRADICTORY one is not: "Rhyzel Bayatin" and
    "Rhyzel Domingo" are positive evidence of two different children, not a
    transcription gap, so they are refused rather than linked.
    """
    if not incoming or not candidate:
        return False
    if incoming[0] != candidate[0]:
        return False
    shorter, longer = sorted((incoming, candidate), key=len)
    return all(token in longer for token in shorter)


def _blank_to_none(value):
    return value or None


def _find_child_match(first_name, middle_name, last_name, date_of_birth, household=None):
    """Look for the Person a child entry already refers to (CRITICAL 1).

    Both parents' forms list the same children, so approving the second
    parent must reuse the child the first parent's approval created rather
    than build a second one.

    BUG (2026-08-23, middle names): this used to compare `first_name`
    exactly, which meant the same child written "Rhyzel Bayatin Abaigar" on
    one form and "Rhyzel Abaigar" on the other never matched -- and, because
    no candidate turned up at all, it reported "no match" rather than
    "ambiguous" and created a duplicate silently. Matching now works on
    three signals instead of two:

      * the surname,
      * the given names as a token list, so a middle name may be present on
        one side and absent on the other (see _names_are_compatible for why
        a *different* middle name still refuses), and
      * the date of birth, which is what narrows a name to one person.

    Plus a fourth when it is available: `household`. A child is always being
    recorded from a parent's form, so where two same-named, same-aged
    candidates exist, one already in this family's household is the one
    meant and an unrelated namesake is not. This narrows genuine ambiguity;
    it never widens a match that the name and birthdate did not already
    allow.

    Returns (person_or_None, ambiguous). `ambiguous` is True whenever a
    plausible candidate exists but cannot be narrowed to exactly one: more
    than one survives, every candidate's birthdate disagrees, or this
    child's own birthdate is missing so nothing could be compared. R30
    stands -- the caller refuses rather than guessing, and the reviewer
    resolves it.
    """
    last_name = (last_name or "").strip()
    incoming = _given_name_tokens(first_name, middle_name)
    if not last_name or not incoming:
        return None, False

    # The review form keeps every date as free text (imports/forms.py), so
    # this arrives as "2015-04-04", not a date. The comparison below happens
    # in Python rather than in SQL -- where Django would have coerced it --
    # so it has to be coerced here or every match silently fails.
    date_of_birth = models.DateField().to_python(date_of_birth)

    given = incoming[0]
    # Cast a wide net in SQL -- the given name exactly, or followed by more
    # words, which is the shape the old splitter wrote -- then narrow in
    # Python, where the token comparison can be expressed properly.
    near_misses = list(
        Person.objects.filter(last_name__iexact=last_name).filter(
            Q(first_name__iexact=first_name) | Q(first_name__istartswith=f"{given} ")
        )
    )
    candidates = [
        candidate
        for candidate in near_misses
        if _names_are_compatible(
            incoming, _given_name_tokens(candidate.first_name, candidate.middle_name)
        )
    ]

    if not candidates:
        # Nobody compatible -- but somebody with this first name, this
        # surname and this exact birthday whose middle name contradicts is
        # far more likely a misread middle name than a second child born the
        # same day. Refusing sends it to the reviewer; returning "no match"
        # would silently create the duplicate this function exists to stop.
        if date_of_birth is not None and any(
            candidate.date_of_birth == date_of_birth for candidate in near_misses
        ):
            return None, True
        return None, False

    if date_of_birth is None:
        return None, True

    dated = [c for c in candidates if c.date_of_birth == date_of_birth]
    if len(dated) == 1:
        return dated[0], False
    if len(dated) > 1 and household is not None:
        in_household = [
            c
            for c in dated
            if HouseholdMember.objects.filter(household=household, person=c).exists()
        ]
        if len(in_household) == 1:
            return in_household[0], False
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
    *_, guessed_last = _split_child_name(spouse_name, household_surname)
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
            first_name, middle_name, last_name = _split_child_name(full_name, person.last_name)
            date_of_birth = _blank_to_none(child.get("date_of_birth"))

            match, ambiguous = _find_child_match(
                first_name, middle_name, last_name, date_of_birth, household=household
            )
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
                # The first form to arrive may have left the middle name out
                # (BUG, 2026-08-23: middle names). A later form supplying it
                # is the fuller record, and linking must not discard it --
                # but an existing middle name is never overwritten, since
                # _names_are_compatible already refused anything that
                # contradicts it.
                if middle_name and not child_person.middle_name:
                    child_person.middle_name = middle_name
                    child_person.updated_by = user
                    child_person.full_clean()
                    child_person.save()
                    notices.append(
                        f"Recorded this form's middle name ({middle_name}) on "
                        f"{child_person.full_name}, which had none on file."
                    )
            else:
                child_person = Person(
                    last_name=last_name,
                    first_name=first_name,
                    middle_name=middle_name,
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
