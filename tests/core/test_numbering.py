import pytest
from django.db import IntegrityError, transaction

from core.models import ControlNumberSequence
from core.numbering import next_document_no, next_member_no, reconcile_member_sequence
from people.models import Person


@pytest.mark.django_db
def test_member_numbers_are_sequential_and_carry_no_year():
    assert next_member_no() == "MEM-0001"
    assert next_member_no() == "MEM-0002"


@pytest.mark.django_db
def test_mem_sequence_row_is_unique_at_the_database_level():
    """PostgreSQL treats NULL as distinct in a unique index, so a plain
    UniqueConstraint(fields=["prefix", "year"]) never fires for year=None —
    exactly the sequence MEM- numbers use. This must be enforced by the
    database, not merely by application code, so concurrent allocation can
    never produce two ('MEM', None) sequence rows.
    """
    ControlNumberSequence.objects.create(prefix="MEM", year=None)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ControlNumberSequence.objects.create(prefix="MEM", year=None)


@pytest.mark.django_db
def test_document_numbers_carry_a_year_and_reset_per_year():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("FR", 2026) == "FR-2026-002"
    assert next_document_no("FR", 2027) == "FR-2027-001"


@pytest.mark.django_db
def test_prefixes_do_not_share_a_sequence():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("RB", 2026) == "RB-2026-001"


@pytest.mark.django_db
def test_reconcile_advances_past_a_hand_entered_member_no():
    """A form was already encoded by hand with MEM-0042 before anyone ever
    ran the allocator. Reconciling, then allocating, must continue from
    0043 — not collide with, or ignore, the number already on paper.
    """
    Person.objects.create(first_name="Ana", last_name="Reyes", member_no="MEM-0042")
    reconcile_member_sequence()
    assert next_member_no() == "MEM-0043"


@pytest.mark.django_db
def test_reconcile_ignores_malformed_member_no_values():
    Person.objects.create(first_name="Cy", last_name="Diaz", member_no="MEM-old")
    Person.objects.create(first_name="Dee", last_name="Ong", member_no="TRANSFER-9")
    reconcile_member_sequence()
    assert next_member_no() == "MEM-0001"


@pytest.mark.django_db
def test_reconcile_never_lowers_the_sequence():
    assert next_member_no() == "MEM-0001"
    assert next_member_no() == "MEM-0002"
    reconcile_member_sequence()
    assert next_member_no() == "MEM-0003"


@pytest.mark.django_db
def test_reconcile_is_safe_to_run_repeatedly():
    Person.objects.create(first_name="Eli", last_name="Reyes", member_no="MEM-0007")
    reconcile_member_sequence()
    reconcile_member_sequence()
    reconcile_member_sequence()
    assert next_member_no() == "MEM-0008"
