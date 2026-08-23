"""Reading a Google Forms response sheet directly.

Members can now fill the profiling form in online (docs/ONLINE_FORM.md).
The responses land in a Google Sheet the volunteer downloads and uploads
here — and it is a RUNNING list: new responses append to the same sheet, so
the same file gets uploaded again and again with a few more rows each time.

Two things follow, and they are the whole reason this module exists.

**The sheet is not the AI template and never will be.** Its columns are the
form's own question titles, it has a Timestamp AEGIS has no column for, it
has no Source Image (there is no photograph of an online submission), and
its committee answers arrive as one comma-joined cell rather than twelve.
Converting it by hand before upload is about twenty column operations per
batch, which is exactly where a column gets dragged one across and
twenty-two people get somebody else's birthday.

**Header text drifts.** The form is edited — help text gets added, wording
gets softened — and the response sheet's headers change with it. The very
first export already read "Place of Birth (e.g. Baguio City, La Trinidad)".
So headers are matched on a normalised prefix rather than exact text, and a
question that cannot be matched is reported rather than silently dropped.

Deduplication is on `Timestamp`. A submission's timestamp never changes as
the sheet grows, which makes it the one stable identity available — see
`response_key`.
"""

import datetime as dt
import re

from imports.parsing import ALL_COMMITTEE_NAMES, ImportValidationError

# A response sheet is recognised by what only it has: a Timestamp column,
# plus names. Deliberately not by the consent questions, whose wording the
# church will edit.
TIMESTAMP_HEADER = "timestamp"

# Question title (normalised, before any bracketed aside) -> the entry key
# imports/parsing.py already validates. Anything not listed is ignored,
# which is what lets the church add a question without breaking the import.
FIELD_BY_QUESTION = {
    "last name": "last_name",
    "first name": "first_name",
    "middle name": "middle_name",
    "suffix": "suffix",
    "nickname": "nickname",
    "date of birth": "date_of_birth",
    "place of birth": "place_of_birth",
    "sex": "gender",
    "gender": "gender",
    "civil status": "civil_status",
    "nationality": "nationality",
    "home address": "home_address",
    "mobile number": "mobile_number",
    "email": "email",
    "spouse name": "spouse_name",
    "date of marriage": "date_of_marriage",
    "emergency contact name": "emergency_contact_name",
    "emergency contact relationship": "emergency_relationship",
    "emergency contact number": "emergency_number",
}

CHILD_NAME_RE = re.compile(r"^child (\d+) name$")
CHILD_DOB_RE = re.compile(r"^child (\d+) date of birth$")

# The two consent questions. Matched on a distinctive fragment rather than
# the full sentence, because the full sentence is long and will be reworded.
CONSENT_FRAGMENT = "consent to"
FACEBOOK_FRAGMENT = "facebook"
COMMITTEE_FRAGMENT = "committees you wish"
NOTES_FRAGMENT = "anything else"

# Google Forms multiple-choice answers, matched on their first word.
AFFIRMATIVE = ("yes",)

# The online form is v3 -- it is the version that carries the Facebook
# question (docs/ONLINE_FORM.md). Nothing else produces this shape.
ONLINE_FORM_VERSION = "v3"


def _normalise(header) -> str:
    """Lowercase, collapsed, and with any bracketed aside removed.

    "Place of Birth (e.g. Baguio City, La Trinidad)" and "Place of Birth"
    are the same question, and the church will keep editing which of the
    two it is.
    """
    text = str(header or "").strip().lower()
    text = re.split(r"\s*[\(\[]", text, maxsplit=1)[0]
    return " ".join(text.split()).rstrip(":?.")


def looks_like_response_sheet(headers) -> bool:
    normalised = {_normalise(header) for header in headers}
    if TIMESTAMP_HEADER not in normalised:
        return False
    return {"last name", "first name"} <= normalised


def _cell(value) -> str:
    """One cell as the text AEGIS expects, with dates normalised.

    Google Forms date answers come back from openpyxl as real datetimes and
    from a CSV as "8/23/2026", neither of which is the YYYY-MM-DD the rest
    of the import speaks.
    """
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ""
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        month, day, year = (int(part) for part in match.groups())
        try:
            return dt.date(year, month, day).isoformat()
        except ValueError:
            # An impossible date is the reviewer's to see, not this
            # function's to silently correct (docs/IMPORT_TEMPLATE.md).
            return text
    return text


def response_key(timestamp_value) -> str:
    """The stable identity of one response.

    A submission's timestamp is fixed when it is submitted and never moves
    as later responses append to the sheet, so re-uploading the running
    list stages only what is new. Two people submitting in the same second
    would collide; for a congregation of this size that is not a risk worth
    designing around, and the reviewer would see one row rather than two
    either way.
    """
    return _cell(timestamp_value)[:64]


def _is_yes(value) -> bool:
    text = _cell(value).lower()
    return any(text.startswith(word) for word in AFFIRMATIVE)


def _committees(value) -> list:
    """The one comma-joined checkbox cell, back into committee names.

    Matched against the church's own list rather than trusted, so a
    renamed committee is reported at upload instead of failing at approval.
    """
    raw = _cell(value)
    if not raw:
        return [], []
    chosen, unknown = [], []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        match = next(
            (known for known in ALL_COMMITTEE_NAMES if known.lower() == name.lower()),
            None,
        )
        if match:
            chosen.append(match)
        else:
            unknown.append(name)
    return chosen, unknown


def parse_response_rows(rows) -> list:
    """Turn a response sheet into the entry dicts the rest of imports uses.

    `rows` is the sheet including its header row. Returns entries carrying
    an extra `_source_key`, which imports/admin.py strips off and stores on
    the staged row so a re-upload of the running list skips what it has
    already seen.
    """
    if not rows:
        raise ImportValidationError(["That file has no rows in it at all."])

    headers = [_normalise(header) for header in rows[0]]
    index_of = {header: position for position, header in enumerate(headers)}

    missing = [name for name in ("last name", "first name") if name not in index_of]
    if missing:
        raise ImportValidationError(
            [
                "This looks like a Google Forms export but is missing the "
                + ", ".join(missing)
                + " question. Check the form still asks for it."
            ]
        )

    def find(fragment):
        return next(
            (position for header, position in index_of.items() if fragment in header),
            None,
        )

    consent_at = find(CONSENT_FRAGMENT)
    facebook_at = find(FACEBOOK_FRAGMENT)
    committees_at = find(COMMITTEE_FRAGMENT)
    notes_at = find(NOTES_FRAGMENT)
    timestamp_at = index_of.get(TIMESTAMP_HEADER)

    entries = []
    errors = []
    for row_number, row in enumerate(rows[1:], start=2):
        if all(_cell(value) == "" for value in row):
            continue

        def value_at(position):
            if position is None or position >= len(row):
                return ""
            return _cell(row[position])

        entry = {key: "" for key in FIELD_BY_QUESTION.values()}
        for header, position in index_of.items():
            key = FIELD_BY_QUESTION.get(header)
            if key:
                entry[key] = value_at(position)

        # Sex is asked as "Male"/"Female"; AEGIS stores MALE/FEMALE.
        entry["gender"] = entry.get("gender", "").upper()
        entry["civil_status"] = entry.get("civil_status", "").upper()

        children = {}
        for header, position in index_of.items():
            name_match = CHILD_NAME_RE.match(header)
            dob_match = CHILD_DOB_RE.match(header)
            if name_match:
                children.setdefault(int(name_match.group(1)), {})["full_name"] = value_at(position)
            elif dob_match:
                children.setdefault(int(dob_match.group(1)), {})["date_of_birth"] = value_at(position)
        entry["children"] = [
            {
                "full_name": child.get("full_name", ""),
                "date_of_birth": child.get("date_of_birth", ""),
            }
            for _, child in sorted(children.items())
            if child.get("full_name") or child.get("date_of_birth")
        ]

        committees, unknown = _committees(value_at(committees_at))
        entry["committees"] = committees
        if unknown:
            errors.append(
                f"Row {row_number}: "
                + ", ".join(f"'{name}'" for name in unknown)
                + " is not a committee AEGIS knows. Check the form's checkbox "
                "wording against the church's committee names."
            )

        # A member who did not consent is not staged at all. The online form
        # skips the rest of its questions for them, so there is nothing to
        # record, and holding their name would be the exact thing they
        # declined.
        if consent_at is not None and not _is_yes(value_at(consent_at)):
            continue

        entry["form_version"] = ONLINE_FORM_VERSION
        entry["consent_given"] = True
        entry["public_greeting_consent"] = (
            _is_yes(value_at(facebook_at)) if facebook_at is not None else False
        )

        submitted = value_at(timestamp_at)
        # The submission date IS the date filed for an online form -- there
        # is no paper, and no separate certification.
        entry["date_filed"] = submitted[:10]
        entry["certification_date"] = submitted[:10]

        entry["source_image"] = ""
        entry["member_no"] = ""
        entry["notes"] = value_at(notes_at)
        entry["confidence"] = "high"  # typed by the member, not read off handwriting
        entry["flagged_fields"] = []
        entry["_source_key"] = response_key(row[timestamp_at]) if timestamp_at is not None else ""

        if not entry["last_name"] or not entry["first_name"]:
            errors.append(
                f"Row {row_number}: no name. Every response needs a last name "
                "and a first name."
            )
            continue

        entries.append(entry)

    if errors:
        raise ImportValidationError(errors)
    if not entries:
        raise ImportValidationError(
            [
                "No responses in that file could be staged. If everyone in it "
                "declined the data privacy consent, that is the correct "
                "outcome and there is nothing to import."
            ]
        )
    return entries
