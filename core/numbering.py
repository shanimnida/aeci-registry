from django.db import transaction

from core.models import ControlNumberSequence


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


def next_member_no() -> str:
    """Member numbers are permanent identity and carry no year (spec D10)."""
    return f"MEM-{_allocate('MEM', None):04d}"


def next_document_no(prefix: str, year: int) -> str:
    """Document numbers are filed per year and reset annually (spec D10)."""
    return f"{prefix}-{year}-{_allocate(prefix, year):03d}"
