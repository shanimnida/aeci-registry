import pytest

from core.numbering import next_document_no, next_member_no


@pytest.mark.django_db
def test_member_numbers_are_sequential_and_carry_no_year():
    assert next_member_no() == "MEM-0001"
    assert next_member_no() == "MEM-0002"


@pytest.mark.django_db
def test_document_numbers_carry_a_year_and_reset_per_year():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("FR", 2026) == "FR-2026-002"
    assert next_document_no("FR", 2027) == "FR-2027-001"


@pytest.mark.django_db
def test_prefixes_do_not_share_a_sequence():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("RB", 2026) == "RB-2026-001"
