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

from people.models import Person

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


def compare(left, right) -> DuplicatePair:
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
    from imports.services import _given_name_tokens, _names_are_compatible

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
                if _names_are_compatible(
                    _given_name_tokens(left.first_name, left.middle_name),
                    _given_name_tokens(right.first_name, right.middle_name),
                ):
                    pairs.append(compare(left, right))
                    if limit and len(pairs) >= limit:
                        return pairs
    return pairs


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
