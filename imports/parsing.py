"""Validates an uploaded JSON file against the shape docs/IMPORT_TEMPLATE.md
tells the AI to produce.

This module never touches the database and never touches people.Person. Its
only job is: does this file parse, and does every entry have the shape
AEGIS can stage? If not, say exactly which entry and which field, so the
volunteer can go back to the AI (or the paper form) rather than stare at a
stack trace. See ImportValidationError.
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


def _check_optional_string(entry, label, field, errors):
    value = entry.get(field)
    if value is not None and not isinstance(value, str):
        errors.append(f"{label}: '{field}' must be text or null, not {type(value).__name__}.")


def _check_date_shaped(entry, label, field, errors):
    value = entry.get(field)
    if value is None:
        return
    if not isinstance(value, str) or not DATE_RE.match(value):
        errors.append(
            f"{label}: '{field}' must be a date in YYYY-MM-DD form or null, got {value!r}."
        )


def _check_enum(entry, label, field, allowed, errors, *, required=False):
    value = entry.get(field)
    if value is None:
        if required:
            errors.append(f"{label}: '{field}' is required and cannot be null.")
        return
    if value not in allowed:
        options = ", ".join(allowed)
        errors.append(f"{label}: '{field}' was {value!r}, must be one of {options}.")


def _check_committees(entry, label, errors):
    committees = entry.get("committees", [])
    if committees is None:
        committees = []
    if not isinstance(committees, list):
        errors.append(f"{label}: 'committees' must be a list.")
        return
    for name in committees:
        if not isinstance(name, str) or name not in ALL_COMMITTEE_NAMES:
            errors.append(
                f"{label}: '{name}' in 'committees' is not one of the twelve committee names."
            )


def _check_children(entry, label, errors):
    children = entry.get("children", [])
    if children is None:
        children = []
    if not isinstance(children, list):
        errors.append(f"{label}: 'children' must be a list.")
        return
    for position, child in enumerate(children, start=1):
        child_label = f"{label}, child {position}"
        if not isinstance(child, dict):
            errors.append(f"{child_label}: each child must be a JSON object.")
            continue
        full_name = child.get("full_name")
        if not full_name or not isinstance(full_name, str):
            errors.append(f"{child_label}: 'full_name' is required and cannot be blank.")
        dob = child.get("date_of_birth")
        if dob is not None and (not isinstance(dob, str) or not DATE_RE.match(dob)):
            errors.append(
                f"{child_label}: 'date_of_birth' must be YYYY-MM-DD or null, got {dob!r}."
            )


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


def _validate_entry(entry, index: int, errors: list[str]):
    label = _label_for(entry, index)
    if not isinstance(entry, dict):
        errors.append(f"{label}: each entry must be a JSON object, not {type(entry).__name__}.")
        return

    for field in REQUIRED_STRING_FIELDS:
        value = entry.get(field)
        if not value or not isinstance(value, str):
            errors.append(f"{label}: '{field}' is required and cannot be blank.")

    for field in OPTIONAL_STRING_FIELDS:
        _check_optional_string(entry, label, field, errors)

    for field in DATE_SHAPED_FIELDS:
        _check_date_shaped(entry, label, field, errors)

    _check_enum(entry, label, "form_version", FORM_VERSIONS, errors, required=True)
    _check_enum(entry, label, "confidence", CONFIDENCE_LEVELS, errors, required=True)
    _check_enum(entry, label, "gender", GENDERS, errors)
    _check_enum(entry, label, "civil_status", CIVIL_STATUSES, errors)

    _check_committees(entry, label, errors)
    _check_children(entry, label, errors)
    _check_uncertain_fields(entry, label, errors)


def parse_import_json(raw_bytes: bytes) -> list[dict]:
    """Parse and shape-validate an uploaded file.

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

    if not isinstance(data, list):
        raise ImportValidationError(
            [f"The file must contain a JSON array of entries, not a {type(data).__name__}."]
        )
    if not data:
        raise ImportValidationError(["The file contains no entries."])

    errors: list[str] = []
    for index, entry in enumerate(data):
        _validate_entry(entry, index, errors)

    if errors:
        raise ImportValidationError(errors)

    return data
