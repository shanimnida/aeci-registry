"""Possible identities for the private staff review screen, never a verdict."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from people.models import MembershipStatus, Person


def _date(value):
    try:
        return models.DateField().to_python(value or None)
    except ValidationError:
        return None  # The ordinary approval validation reports invalid dates.


def child_candidates(first_name, middle_name, last_name, date_of_birth):
    from .services import _given_name_tokens, _names_are_compatible

    incoming = _given_name_tokens(first_name, middle_name)
    if not incoming or not (last_name or "").strip():
        return []
    dob = _date(date_of_birth)
    near = Person.objects.filter(last_name__iexact=last_name.strip()).filter(
        Q(first_name__iexact=incoming[0]) | Q(first_name__istartswith=f"{incoming[0]} ")
    )
    return [
        person for person in near
        if _names_are_compatible(incoming, _given_name_tokens(person.first_name, person.middle_name))
        or (dob is not None and person.date_of_birth == dob)
    ]


def subject_candidates(data):
    # A person's own form can enrich their earlier child record. Ordinary
    # adult duplicate warnings continue to be advisory, without merging adults.
    return [
        person for person in child_candidates(
            data.get("first_name"), data.get("middle_name"),
            data.get("last_name"), data.get("date_of_birth"),
        ) if person.guardian_id or person.membership_status == MembershipStatus.CHILD
    ]


def spouse_candidates(name, surname, exclude_pk=None):
    from .services import _split_child_name

    name = " ".join((name or "").split())
    if not name:
        return []
    *_, last = _split_child_name(name, surname or "")
    return [
        person for person in Person.objects.filter(last_name__iexact=last).exclude(pk=exclude_pk)
        if person.first_name.strip() and name.lower().startswith(person.first_name.strip().lower())
    ]


def candidate_label(person):
    dob = str(person.date_of_birth) if person.date_of_birth else "birth date not recorded"
    return f"Link to {person.full_name} — {dob} — record #{person.pk} ({person.get_membership_status_display()})"


def resolve_choice(choice, candidates, *, label, required=True):
    """Revalidate against current server candidates, including after a race."""
    if choice == "new":
        return None
    for candidate in candidates:
        if choice == f"link:{candidate.pk}":
            return candidate
    if choice:
        raise ValidationError(f"The selected record for {label} is no longer a possible match. Review it again.")
    if candidates and required:
        raise ValidationError(f"Choose whether {label} is a separate person or one of the possible existing records.")
    return None
