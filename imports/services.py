"""Turns reviewer-approved import data into real register rows.

Every object built here is full_clean()-ed before it is saved, and the
whole thing runs inside one transaction. If any piece is refused -- an
impossible date, a third self-selected committee, a second chairperson --
nothing written by this call survives: the caller catches the
ValidationError, shows it against that person, and the row stays pending.
This is the one non-admin write path the church's committee rules (at most
two self-selected committees, one chairperson per committee) have to be
enforced against, since those rules live in CommitteeMembership.clean() and
nowhere else.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from people.admin import find_possible_duplicates
from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person


def _split_child_name(full_name: str, parent_last_name: str) -> tuple[str, str]:
    """Best-effort split of a child's one-string full name into (first, last).

    docs/IMPORT_TEMPLATE.md's `children` entries carry only `full_name` --
    there is no separate surname field to transcribe, because the paper form
    itself only has one blank per child. If the name ends with the parent's
    own last name (the common case), that becomes the child's last name and
    the rest is first/middle name. Otherwise the last word is treated as the
    surname. Either way this is a guess: the reviewer sees it as an editable
    field before approving and can correct it.
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


def build_person_from_import(cleaned: dict, children: list[dict], user) -> Person:
    """Create the Person, Household, child Persons and CommitteeMemberships
    for one approved import row. Returns the created Person.

    `cleaned` is the reviewer's (possibly corrected) data for the primary
    person, keyed the same as docs/IMPORT_TEMPLATE.md's JSON shape plus
    `membership_status` (a reviewer decision the AI never makes -- see
    import-feature-report.md). `children` is a list of {full_name,
    date_of_birth} dicts, same shape as the JSON's `children` array.
    """
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

        for child in children:
            full_name = (child.get("full_name") or "").strip()
            if not full_name:
                continue
            first_name, last_name = _split_child_name(full_name, person.last_name)
            child_person = Person(
                last_name=last_name,
                first_name=first_name,
                date_of_birth=_blank_to_none(child.get("date_of_birth")),
                membership_status=MembershipStatus.CHILD,
                guardian=person,
                nationality=person.nationality,
                created_by=user,
                updated_by=user,
            )
            child_person.full_clean()
            child_person.save()

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

        return person


def duplicate_warning(person: Person) -> str | None:
    """Mirrors people.admin.PersonAdmin.save_model's soft duplicate warning,
    so the import path and the ordinary admin form give the same signal."""
    duplicates = find_possible_duplicates(person)
    if not duplicates.exists():
        return None
    names = ", ".join(str(candidate) for candidate in duplicates[:3])
    return f"This may duplicate an existing record: {names}. Approved anyway — check and merge by hand if it is the same person."
