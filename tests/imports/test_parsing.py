import json
from pathlib import Path

import pytest

from imports.parsing import ImportValidationError, parse_import_json

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_a_well_formed_file_parses_into_the_right_number_of_entries():
    entries = parse_import_json(_read("well_formed_import.json"))
    assert len(entries) == 3
    assert entries[0]["last_name"] == "DELACRUZ"
    assert entries[0]["first_name"] == "JUAN MIGUEL"


def test_malformed_json_syntax_is_rejected_with_a_clear_message():
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(_read("malformed_syntax.json"))
    errors = exc_info.value.errors
    assert len(errors) == 1
    assert "not valid JSON" in errors[0]


def test_bad_shape_entries_are_named_not_stack_traced():
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(_read("bad_shape.json"))
    errors = exc_info.value.errors
    joined = "\n".join(errors)
    # Every complaint must name the offending entry by its source image, not
    # a bare index or a traceback.
    assert all("IMG_9020.jpg" in error for error in errors)
    assert "last_name" in joined
    assert "gender" in joined
    assert "date_of_birth" in joined
    assert "committees" in joined
    assert "confidence" in joined
    assert "children" in joined


def test_top_level_must_be_a_json_array():
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(json.dumps({"not": "a list"}).encode())
    assert "must contain a JSON array" in exc_info.value.errors[0]


def test_an_empty_array_is_rejected():
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(b"[]")
    assert "no entries" in exc_info.value.errors[0]


def test_grievance_and_reconciliation_is_accepted_even_though_appointed_only():
    entry = json.loads(_read("well_formed_import.json").decode())[0]
    entry["committees"] = ["Grievance and Reconciliation"]
    entries = parse_import_json(json.dumps([entry]).encode())
    assert entries[0]["committees"] == ["Grievance and Reconciliation"]


def test_an_unknown_committee_name_is_rejected():
    entry = json.loads(_read("well_formed_import.json").decode())[0]
    entry["committees"] = ["Music and Arts Committee"]  # not the exact seeded name
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(json.dumps([entry]).encode())
    assert "Music and Arts Committee" in exc_info.value.errors[0]


def test_deeply_nested_json_is_rejected_gracefully_not_a_raw_500():
    """IMPORTANT 6: json.loads() has no depth limit of its own -- 10,000
    levels of nesting raises an uncaught RecursionError past the point this
    module used to catch only json.JSONDecodeError."""
    hostile = ("[" * 10_000) + ("]" * 10_000)
    with pytest.raises(ImportValidationError) as exc_info:
        parse_import_json(hostile.encode())
    assert exc_info.value.errors


def test_an_impossible_calendar_date_still_parses_shape_only():
    """docs/IMPORT_TEMPLATE.md rule 3: the AI records an impossible date as
    written and flags it, rather than fixing or dropping it. Shape
    validation only checks YYYY-MM-DD form -- calendar validity is refused
    later, at approval time, against the real Person.date_of_birth field.
    """
    entry = json.loads(_read("well_formed_import.json").decode())[0]
    entry["date_of_birth"] = "1985-02-29"  # not a leap year
    entries = parse_import_json(json.dumps([entry]).encode())
    assert entries[0]["date_of_birth"] == "1985-02-29"
