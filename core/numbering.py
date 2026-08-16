import re

from django.db import transaction

from core.models import ControlNumberSequence

# Matches exactly "MEM-" followed by digits, e.g. "MEM-0042". Anything else
# (blank, a different prefix, a legacy format, a typo) does not match and is
# ignored by reconcile_member_sequence rather than raising.
MEMBER_NO_RE = re.compile(r"^MEM-(\d+)$")


def _allocate(prefix: str, year: int | None) -> int:
    """Reserve and return the next integer for this sequence.

    Runs inside a transaction with a row lock so two people encoding at the
    same time cannot be handed the same number.
    """
    with transaction.atomic():
        ControlNumberSequence.objects.get_or_create(prefix=prefix, year=year)
        sequence = ControlNumberSequence.objects.select_for_update().get(
            prefix=prefix, year=year
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return sequence.last_value


def _highest_assigned_member_number() -> int:
    """Highest numeric suffix among Person.member_no values already on file.

    Values that don't look like "MEM-<digits>" (blank, malformed, a legacy
    format) are ignored rather than raising, since paper-form encoding is
    not guaranteed to be clean.

    Imported locally, not at module level: core is a foundational app and
    must not hard-depend on people at import time (avoids app-registry
    ordering issues and a module-level layering violation).
    """
    from people.models import Person

    highest = 0
    member_nos = Person.objects.filter(
        member_no__startswith="MEM-"
    ).values_list("member_no", flat=True)
    for value in member_nos:
        match = MEMBER_NO_RE.match(value)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def reconcile_member_sequence() -> int:
    """Advance the MEM control number sequence past any hand-entered numbers.

    Secretariat staff sometimes type a MEM- number straight from a paper
    form instead of using "Assign member numbers", so
    ControlNumberSequence.last_value for MEM can fall behind what's already
    on file. This raises last_value to at least the highest numeric suffix
    found on any Person.member_no. It never lowers last_value, and it takes
    the same row lock next_member_no uses, so it is safe to call any number
    of times, including repeatedly or concurrently with allocation.

    Deliberately NOT called from next_member_no(): the cost is a full scan
    of Person.member_no, and running it on every single allocation (e.g.
    once per row inside a bulk "assign member numbers" admin action) turns
    an O(1) increment into an O(members) scan per row for no benefit once
    a volunteer has run this command after a batch of hand encoding. It is
    exposed as a management command (see
    core/management/commands/reconcile_member_sequence.py) for exactly
    that workflow: run it once after a batch of paper-form encoding, before
    the next "Assign member numbers" pass.

    Returns the resulting last_value.
    """
    floor = _highest_assigned_member_number()
    with transaction.atomic():
        ControlNumberSequence.objects.get_or_create(prefix="MEM", year=None)
        sequence = ControlNumberSequence.objects.select_for_update().get(
            prefix="MEM", year=None
        )
        if sequence.last_value < floor:
            sequence.last_value = floor
            sequence.save(update_fields=["last_value"])
        return sequence.last_value


def next_member_no() -> str:
    """Member numbers are permanent identity and carry no year (spec D10).

    Does NOT reconcile automatically — see reconcile_member_sequence for
    why that is a deliberate choice, not an oversight.
    """
    return f"MEM-{_allocate('MEM', None):04d}"


def next_document_no(prefix: str, year: int) -> str:
    """Document numbers are filed per year and reset annually (spec D10)."""
    return f"{prefix}-{year}-{_allocate(prefix, year):03d}"
