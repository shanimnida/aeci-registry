"""Finding people who are probably the same person, and showing the pair
side by side so a human can decide.

Requested 2026-08-24 after two real cases in one week: a child written with
a middle name on one parent's form and without it on the other's, and a
committee chairperson seeded from the Board minutes who then filled in her
own profiling form. The second is not an accident of the data — it is
structural. `seed_officers` deliberately creates a bare Person for every
officer named in the minutes, and every one of those people will eventually
submit a form.

Two deliberate limits, both from spec 1.2:

- **This finds and compares. It does not decide.** The completeness score
  says which record holds more, never which record is right — a shorter
  record can be the correct one and a fuller one can be full of a
  transcription error.
- **Merging is not automatic.** What `merge_into` does is move the things
  that would otherwise be destroyed — committee service, household places,
  scanned forms — onto the record the human chose to keep, and nothing else.
  It never copies field values between people, because deciding whose
  birthdate is right is exactly the judgement the human is there to make.
"""

from dataclasses import dataclass

from django.db import transaction

from people.models import Household, Person

# What "more complete" means. TRACKED_FIELDS is the church's own answer --
# it is the list the follow-up queue chases (spec 6.3) -- extended with the
# identity fields that distinguish two records of the same person rather
# than measuring how filled-in they are.
COMPLETENESS_FIELDS = (
    "member_no",
    "middle_name",
    "nickname",
    "date_of_birth",
    "place_of_birth",
    "gender",
    "civil_status",
    "home_address",
    "mobile_number",
    "email",
    "emergency_contact_name",
    "emergency_contact_number",
    "date_filed",
    "date_became_member",
)


@dataclass(frozen=True)
class FieldComparison:
    label: str
    left: str
    right: str
    agree: bool
    only_one_has_it: bool


@dataclass(frozen=True)
class DuplicatePair:
    left: Person
    right: Person
    left_score: int
    right_score: int
    fields: list
    left_attachments: dict
    right_attachments: dict
    reason: str = "Same surname and a compatible given name."

    @property
    def fuller(self):
        """The record holding more, or None when they hold the same amount.

        Named `fuller` rather than `better` on purpose. It is a count of
        filled-in fields and nothing more; the reviewer decides which record
        is right.
        """
        if self.left_score > self.right_score:
            return self.left
        if self.right_score > self.left_score:
            return self.right
        return None

    @property
    def conflicts(self) -> list:
        """Fields where both records have a value and the values differ.

        The reviewer's real work. Anything here means one of the two is
        wrong, and deleting the wrong one loses the right answer.
        """
        return [field for field in self.fields if not field.agree and not field.only_one_has_it]


def completeness(person) -> int:
    return sum(1 for field in COMPLETENESS_FIELDS if getattr(person, field, None))


def _display(person, field_name) -> str:
    value = getattr(person, field_name, None)
    if value in (None, ""):
        return ""
    getter = getattr(person, f"get_{field_name}_display", None)
    return str(getter() if getter else value)


def attachments(person) -> dict:
    """What would be destroyed if this record were deleted.

    Committee memberships and household places cascade; form scans point at
    an image in object storage. Counting them is how the reviewer sees that
    deleting the *seeded chairperson* costs a committee role, which is
    exactly the mistake this screen exists to prevent.
    """
    return {
        "committees": person.committee_memberships.count(),
        "households": person.household_memberships.count(),
        "scans": person.scans.count(),
        "wards": person.wards.count(),
    }


def _within_one_edit(one: str, other: str) -> bool:
    """True when two words differ by a single typo.

    One insertion, deletion or substitution, or two adjacent letters
    swapped -- "Jonhmar" and "Johnmar", which is what a hand copying a name
    off a form actually produces.

    Used ONLY as a finder: a near-miss is shown to a human, never linked
    automatically. Restricted to words of four letters or more, because
    below that a single edit is most of the word and "Ana"/"Ann" are two
    real names.
    """
    one, other = one.lower(), other.lower()
    if one == other:
        return False
    if min(len(one), len(other)) < 4 or abs(len(one) - len(other)) > 1:
        return False
    if len(one) == len(other):
        differing = [i for i in range(len(one)) if one[i] != other[i]]
        if len(differing) == 1:
            return True
        if len(differing) == 2:
            first, second = differing
            return (
                second == first + 1
                and one[first] == other[second]
                and one[second] == other[first]
            )
        return False
    shorter, longer = sorted((one, other), key=len)
    for position in range(len(longer)):
        if longer[:position] + longer[position + 1 :] == shorter:
            return True
    return False


def compare(left, right, reason=None) -> DuplicatePair:
    fields = []
    for field_name in COMPLETENESS_FIELDS:
        left_value = _display(left, field_name)
        right_value = _display(right, field_name)
        fields.append(
            FieldComparison(
                label=Person._meta.get_field(field_name).verbose_name.title(),
                left=left_value,
                right=right_value,
                agree=left_value == right_value,
                only_one_has_it=bool(left_value) != bool(right_value),
            )
        )
    return DuplicatePair(
        left=left,
        right=right,
        left_score=completeness(left),
        right_score=completeness(right),
        fields=fields,
        left_attachments=attachments(left),
        right_attachments=attachments(right),
        **({"reason": reason} if reason else {}),
    )


def find_duplicate_pairs(limit=None) -> list:
    """Every pair of people who look like the same person.

    Matched on first and last name, case-insensitively, with the middle
    name compared the same forgiving way child linking does (see
    imports.services._names_are_compatible): a middle name missing on one
    side is a transcription gap, and it is how the Abaigar pair was created
    in the first place.

    Deliberately NOT matched on birthdate: half the register has none, and
    the seeded officers have none by construction, so requiring one would
    miss precisely the duplicates that actually occur.
    """
    people = list(
        Person.objects.all()
        .order_by("last_name", "first_name", "pk")
        .prefetch_related("committee_memberships", "household_memberships", "scans")
    )
    by_surname = {}
    for person in people:
        by_surname.setdefault(person.last_name.strip().lower(), []).append(person)

    pairs = []
    for group in by_surname.values():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                reason = _person_pair_reason(left, right)
                if reason is None:
                    continue
                pairs.append(compare(left, right, reason=reason))
                if limit and len(pairs) >= limit:
                    return pairs
    return pairs


def _person_pair_reason(left, right):
    """Why these two might be one person, or None.

    Two signals, and the second is deliberately weaker. Compatible names
    (which now includes a middle INITIAL standing for the middle name it
    abbreviates) is the strong one and is what the importer itself links
    on. A first name one typo away is a finder only -- "Jonhmar" and
    "Johnmar" are the same child written twice, and nothing but a person
    reading them can be sure of that.
    """
    from imports.services import _given_name_tokens, _names_are_compatible

    if _names_are_compatible(
        _given_name_tokens(left.first_name, left.middle_name),
        _given_name_tokens(right.first_name, right.middle_name),
    ):
        return "Same surname and a compatible given name."

    left_first = (left.first_name or "").split()[:1]
    right_first = (right.first_name or "").split()[:1]
    if left_first and right_first and _within_one_edit(left_first[0], right_first[0]):
        return (
            f"Same surname, and the first names differ by one letter "
            f"({left_first[0]} / {right_first[0]}) — probably a typo, but "
            "check before merging."
        )
    return None


@transaction.atomic
def merge_into(keep, remove) -> dict:
    """Move everything attached to `remove` onto `keep`, then delete it.

    Only attachments move. No field value is ever copied from one person to
    the other: deciding whose birthdate is right is the judgement the
    reviewer is there to make, and a merge that quietly overwrote the kept
    record's fields would be making it for them.

    A membership on a committee `keep` is already on is dropped rather than
    moved -- one person holds one role on a committee at a time (see
    CommitteeMembership._check_one_role_per_committee), and this is where
    the seeded chairperson meets her own imported form: she is Chairperson
    on one row and Member on the other, and Chairperson is the one worth
    keeping.
    """
    from committees.models import CommitteeMembership, CommitteeRole
    from people.models import HouseholdMember

    moved = {"committees": 0, "households": 0, "scans": 0, "dropped": 0}

    # Appointed roles outrank a plain membership when both records name the
    # same committee -- being seeded as Chairperson and then ticking that
    # committee on your own form is one person, one committee, and the
    # appointment is the fact worth keeping.
    kept_roles = {
        membership.committee_id: membership
        for membership in CommitteeMembership.objects.filter(person=keep)
    }
    for membership in CommitteeMembership.objects.filter(person=remove):
        existing = kept_roles.get(membership.committee_id)
        if existing is None:
            membership.person = keep
            membership.save(update_fields=["person"])
            kept_roles[membership.committee_id] = membership
            moved["committees"] += 1
            continue
        if (
            membership.role in CommitteeMembership.APPOINTED_ROLES
            and existing.role == CommitteeRole.MEMBER
        ):
            existing.delete()
            membership.person = keep
            membership.save(update_fields=["person"])
            kept_roles[membership.committee_id] = membership
            moved["committees"] += 1
        else:
            moved["dropped"] += 1

    kept_households = set(
        HouseholdMember.objects.filter(person=keep).values_list("household_id", flat=True)
    )
    for place in HouseholdMember.objects.filter(person=remove):
        if place.household_id in kept_households:
            moved["dropped"] += 1
            continue
        place.person = keep
        place.save(update_fields=["person"])
        kept_households.add(place.household_id)
        moved["households"] += 1

    moved["scans"] = remove.scans.update(person=keep)
    Person.objects.filter(guardian=remove).update(guardian=keep)
    Person.objects.filter(approved_by=remove).update(approved_by=keep)

    remove.delete()
    return moved


# -- households ---------------------------------------------------------
#
# Added 2026-08-24. The duplicate-household bug (see imports/services.py,
# "the Reyes case") wrote real pairs to the register before it was fixed,
# and fixing the importer does nothing about those. Merging households is
# genuinely simpler than merging people: a household holds a name, an
# address and a wedding date, and everything else about it is its members.


@dataclass(frozen=True)
class HouseholdPair:
    left: Household
    right: Household
    shared: list
    reason: str

    @property
    def fuller(self):
        """The household holding more members, or None on a tie."""
        left_count = self.left.members.count()
        right_count = self.right.members.count()
        if left_count > right_count:
            return self.left
        if right_count > left_count:
            return self.right
        return None


def _household_fields(household) -> list:
    return [
        ("Address", household.address or ""),
        (
            "Date of marriage",
            household.date_of_marriage.isoformat() if household.date_of_marriage else "",
        ),
        ("Members", str(household.members.count())),
    ]


def find_duplicate_household_pairs(limit=None) -> list:
    """Households that are probably one family.

    Two signals, and the first is worth far more than the second:

    - **They share a member.** Somebody recorded in both is not a
      coincidence -- it is exactly what the old bug produced, since the
      second parent's form matched the same children and added them to a
      second household. Near-certain.
    - **Same name and same address, sharing nobody.** Weaker: two unrelated
      Reyes families can share a surname. It is shown, and said to be the
      weaker reason, so the reviewer knows to look harder.

    Name alone is deliberately NOT a signal. "Reyes Family" is a common
    name in this congregation and flagging every pair of them would bury
    the real ones.
    """
    households = list(
        Household.objects.all().prefetch_related("members__person").order_by("pk")
    )
    members = {
        household.pk: {member.person_id for member in household.members.all()}
        for household in households
    }

    pairs = []
    for index, left in enumerate(households):
        for right in households[index + 1 :]:
            shared = members[left.pk] & members[right.pk]
            if shared:
                names = list(
                    Person.objects.filter(pk__in=shared).values_list("pk", flat=True)
                )
                reason = (
                    f"{len(names)} person(s) are recorded in both — that only "
                    "happens when one family was entered twice."
                )
            elif (
                left.name.strip().lower() == right.name.strip().lower()
                and left.address.strip()
                and left.address.strip().lower() == right.address.strip().lower()
            ):
                names = []
                reason = (
                    "Same name and same address, but no member in common — "
                    "weaker evidence, so check before merging."
                )
            else:
                continue

            pairs.append(
                HouseholdPair(
                    left=left,
                    right=right,
                    shared=list(Person.objects.filter(pk__in=names)),
                    reason=reason,
                )
            )
            if limit and len(pairs) >= limit:
                return pairs
    return pairs


@transaction.atomic
def merge_households(keep, remove) -> dict:
    """Move `remove`'s members onto `keep`, then delete it.

    Fills the kept household's address and wedding date only where it has
    none -- the same rule the importer follows, and for the same reason:
    somebody already recorded an answer there and this is not the place to
    overrule it. A member already in `keep` is dropped rather than moved,
    since one person sits in a household once.
    """
    from people.models import HouseholdMember

    moved = {"members": 0, "dropped": 0, "filled": []}

    already = set(
        HouseholdMember.objects.filter(household=keep).values_list("person_id", flat=True)
    )
    for member in HouseholdMember.objects.filter(household=remove):
        if member.person_id in already:
            moved["dropped"] += 1
            continue
        member.household = keep
        member.save(update_fields=["household"])
        already.add(member.person_id)
        moved["members"] += 1

    if not keep.address and remove.address:
        keep.address = remove.address
        moved["filled"].append("address")
    if keep.date_of_marriage is None and remove.date_of_marriage is not None:
        keep.date_of_marriage = remove.date_of_marriage
        moved["filled"].append("date of marriage")
    if moved["filled"]:
        keep.full_clean()
        keep.save()

    remove.delete()
    return moved
