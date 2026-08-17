"""Validates an uploaded file against the shape docs/IMPORT_TEMPLATE.md tells
the AI to produce.

This module never touches the database and never touches people.Person. Its
only job is: does this file parse, and does every entry have the shape
AEGIS can stage? If not, say exactly which entry and which field, so the
volunteer can go back to the AI (or the paper form) rather than stare at a
stack trace. See ImportValidationError.

Two upload formats exist -- JSON (parse_import_json, below) and the
spreadsheet formats .xlsx/.csv (imports/spreadsheet.py). Both funnel into
the same `_validate_entry` so a row from a spreadsheet and an entry from a
JSON array are held to identical rules and get equivalent errors. The only
difference is *how the error names the offending field*: JSON errors name
the JSON key (e.g. 'last_name'), matching every test and doc written
against this module since before spreadsheets existed. The spreadsheet path
passes a `field_labels` mapping so the same errors instead name the column
header a volunteer actually sees in Excel (e.g. 'Last Name') -- see
imports/spreadsheet.py's FIELD_LABELS and docs/IMPORT_TEMPLATE.md.
"""

import json
import re

# The eleven committees a member may self-select (docs/IMPORT_TEMPLATE.md,
# matching committees/migrations/0002_seed_committees.py exactly).
SELF_SELECTABLE_COMMITTEE_NAMES = (
    "Sunshine",
    "General Services",
    "Property and Supplies",
    "Music and Arts",
    "Children's Ministry",
    "Youth",
    "Events",
    "Finance and Resource Accessing",
    "ICT",
    "Secretariat",
    "Food",
)
# The twelfth committee: appointed by the Board, never on the paper form,
# but the AI is told to record it if it sees it ticked anyway.
APPOINTED_ONLY_COMMITTEE_NAME = "Grievance and Reconciliation"
ALL_COMMITTEE_NAMES = SELF_SELECTABLE_COMMITTEE_NAMES + (APPOINTED_ONLY_COMMITTEE_NAME,)

FORM_VERSIONS = ("v1", "v2")
CONFIDENCE_LEVELS = ("high", "medium", "low")
GENDERS = ("MALE", "FEMALE")
CIVIL_STATUSES = ("SINGLE", "MARRIED", "WIDOWED", "SEPARATED", "ANNULLED")

# Shape only -- NOT calendar validity. "1985-02-29" (not a leap year) matches
# this and is deliberately let through: docs/IMPORT_TEMPLATE.md rule 3 tells
# the AI to record an impossible date as written and flag it, not silently
# fix it. AEGIS's own refusal of that date happens later, at approval time,
# against people.Person's real DateField -- see imports/services.py.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_STRING_FIELDS = ("source_image", "last_name", "first_name")
OPTIONAL_STRING_FIELDS = (
    "member_no", "middle_name", "suffix", "place_of_birth", "nationality",
    "home_address", "mobile_number", "email", "spouse_name",
    "emergency_contact_name", "emergency_relationship", "emergency_number",
    "notes",
)
DATE_SHAPED_FIELDS = ("date_filed", "date_of_birth", "date_of_marriage", "certification_date")


class ImportValidationError(Exception):
    """Carries every problem found, not just the first, so one round trip
    to the AI (or one correction pass on the file) can fix everything."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _label_for(entry, index: int) -> str:
    if isinstance(entry, dict) and entry.get("source_image"):
        return f"entry {index + 1} ({entry['source_image']})"
    return f"entry {index + 1}"


def _fmt_field(field: str, field_labels: dict | None) -> str:
    """The quoted name an error message shows for `field`. Identity by
    default (JSON path, and every existing test/doc built around it); the
    spreadsheet path passes a field->column-header mapping so the same
    message names the header a volunteer sees in Excel instead."""
    display = (field_labels or {}).get(field, field)
    return f"'{display}'"


def _check_optional_string(entry, label, field, errors, field_labels=None):
    value = entry.get(field)
    if value is not None and not isinstance(value, str):
        errors.append(
            f"{label}: {_fmt_field(field, field_labels)} must be text or null, "
            f"not {type(value).__name__}."
        )


def _check_date_shaped(entry, label, field, errors, field_labels=None):
    value = entry.get(field)
    if value is None:
        return
    if not isinstance(value, str) or not DATE_RE.match(value):
        errors.append(
            f"{label}: {_fmt_field(field, field_labels)} must be a date in YYYY-MM-DD form "
            f"or null, got {value!r}."
        )


def _check_enum(entry, label, field, allowed, errors, *, required=False, field_labels=None):
    value = entry.get(field)
    if value is None:
        if required:
            errors.append(f"{label}: {_fmt_field(field, field_labels)} is required and cannot be null.")
        return
    if value not in allowed:
        options = ", ".join(allowed)
        errors.append(
            f"{label}: {_fmt_field(field, field_labels)} was {value!r}, must be one of {options}."
        )


def _check_committees(entry, label, errors, field_labels=None):
    committees = entry.get("committees", [])
    if committees is None:
        committees = []
    if not isinstance(committees, list):
        errors.append(f"{label}: {_fmt_field('committees', field_labels)} must be a list.")
        return
    for name in committees:
        if not isinstance(name, str) or name not in ALL_COMMITTEE_NAMES:
            errors.append(
                f"{label}: '{name}' in {_fmt_field('committees', field_labels)} is not one of "
                "the twelve committee names."
            )


def _check_children(entry, label, errors, field_labels=None, child_positions=None):
    """`child_positions`, if given, is the true 1-based paper-form slot
    number for each item in `children` -- needed because the spreadsheet
    path (imports/spreadsheet.py) drops empty slots before this list is
    built, so a filled "Child 2" following a blank "Child 1" would otherwise
    be mislabelled child 1 (list position) instead of child 2 (its real
    slot, and the column header a volunteer actually sees)."""
    children = entry.get("children", [])
    if children is None:
        children = []
    if not isinstance(children, list):
        errors.append(f"{label}: {_fmt_field('children', field_labels)} must be a list.")
        return
    for index, child in enumerate(children):
        position = child_positions[index] if child_positions else index + 1
        child_label = f"{label}, child {position}"
        if not isinstance(child, dict):
            errors.append(f"{child_label}: each child must be a JSON object.")
            continue
        full_name = child.get("full_name")
        if not full_name or not isinstance(full_name, str):
            name_field = _fmt_field(f"child_{position}_name", field_labels) \
                if field_labels and f"child_{position}_name" in field_labels else "'full_name'"
            errors.append(f"{child_label}: {name_field} is required and cannot be blank.")
        dob = child.get("date_of_birth")
        if dob is not None and (not isinstance(dob, str) or not DATE_RE.match(dob)):
            dob_field = _fmt_field(f"child_{position}_date_of_birth", field_labels) \
                if field_labels and f"child_{position}_date_of_birth" in field_labels else "'date_of_birth'"
            errors.append(f"{child_label}: {dob_field} must be YYYY-MM-DD or null, got {dob!r}.")


def _check_uncertain_fields(entry, label, errors):
    uncertain = entry.get("uncertain_fields", [])
    if uncertain is None:
        uncertain = []
    if not isinstance(uncertain, list):
        errors.append(f"{label}: 'uncertain_fields' must be a list.")
        return
    for position, item in enumerate(uncertain, start=1):
        if not isinstance(item, dict):
            errors.append(f"{label}, uncertain_fields[{position}]: must be a JSON object.")


def _validate_entry(
    entry, label: str, errors: list[str], field_labels: dict | None = None,
    child_positions: list[int] | None = None,
):
    """Shared by both upload formats -- see this module's docstring. `label`
    identifies the entry in error text ('entry 3 (IMG_1.jpg)' for JSON,
    'row 4 (IMG_1.jpg)' for a spreadsheet); `field_labels`, if given, maps a
    field's JSON key to the column header an error should name instead.
    `child_positions` is the spreadsheet path's real slot numbers -- see
    _check_children.
    """
    if not isinstance(entry, dict):
        errors.append(f"{label}: each entry must be a JSON object, not {type(entry).__name__}.")
        return

    for field in REQUIRED_STRING_FIELDS:
        value = entry.get(field)
        if not value or not isinstance(value, str):
            errors.append(f"{label}: {_fmt_field(field, field_labels)} is required and cannot be blank.")

    for field in OPTIONAL_STRING_FIELDS:
        _check_optional_string(entry, label, field, errors, field_labels)

    for field in DATE_SHAPED_FIELDS:
        _check_date_shaped(entry, label, field, errors, field_labels)

    _check_enum(entry, label, "form_version", FORM_VERSIONS, errors, required=True, field_labels=field_labels)
    _check_enum(entry, label, "confidence", CONFIDENCE_LEVELS, errors, required=True, field_labels=field_labels)
    _check_enum(entry, label, "gender", GENDERS, errors, field_labels=field_labels)
    _check_enum(entry, label, "civil_status", CIVIL_STATUSES, errors, field_labels=field_labels)

    _check_committees(entry, label, errors, field_labels)
    _check_children(entry, label, errors, field_labels, child_positions)
    _check_uncertain_fields(entry, label, errors)


def parse_import_json(raw_bytes: bytes) -> list[dict]:
    """Parse and shape-validate an uploaded JSON file.

    Returns the list of entries on success. Raises ImportValidationError,
    carrying every problem found, on any failure -- malformed JSON, wrong
    top-level type, or any entry missing what docs/IMPORT_TEMPLATE.md
    requires. Never partially succeeds: either the whole file is usable or
    none of it is staged.
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportValidationError([f"The file is not valid UTF-8 text ({exc})."]) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(
            [f"The file is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."]
        ) from exc
    except RecursionError as exc:
        # IMPORTANT 6: json.loads() has no depth limit of its own -- it
        # recurses once per nesting level and relies on Python's own
        # recursion limit to eventually give up. Verified: 10,000 levels of
        # nesting raises an uncaught RecursionError, which propagated past
        # this module as a raw 500 rather than the graceful, per-entry
        # ImportValidationError this module promises for every other
        # malformed input.
        raise ImportValidationError(
            ["The file is nested far deeper than any real member form -- AEGIS stopped "
             "reading it rather than crash. Check the file was produced correctly."]
        ) from exc
    except ValueError as exc:
        # Defensive: json.loads() can raise plain ValueError too (for
        # example Python's own integer-string conversion limit on a huge
        # numeric literal), not just JSONDecodeError. Same graceful
        # response either way -- hostile or malformed input never reaches
        # the caller as a stack trace.
        raise ImportValidationError([f"The file is not valid JSON: {exc}."]) from exc

    if not isinstance(data, list):
        raise ImportValidationError(
            [f"The file must contain a JSON array of entries, not a {type(data).__name__}."]
        )
    if not data:
        raise ImportValidationError(["The file contains no entries."])

    errors: list[str] = []
    for index, entry in enumerate(data):
        _validate_entry(entry, _label_for(entry, index), errors)

    if errors:
        raise ImportValidationError(errors)

    return data
