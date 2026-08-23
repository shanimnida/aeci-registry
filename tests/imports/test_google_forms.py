"""Reading a Google Forms response sheet, added 2026-08-24.

Members fill the profiling form in online now, and the responses land in a
sheet the volunteer downloads and uploads here. It is a RUNNING list: the
same file comes back with a few more rows each time, so the interesting
behaviour is not parsing but not-re-parsing.

The other thing worth pinning down is header drift. The very first real
export already read "Place of Birth (e.g. Baguio City, La Trinidad)"
because the form had been edited after the script created it, so matching
is on a normalised prefix and there is a test for exactly that shape.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt
import io

import openpyxl
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from imports.googleforms import looks_like_response_sheet, parse_response_rows
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import ImportValidationError
from imports.spreadsheet import parse_import_file
from people.models import MembershipStatus, Person

CONSENT_Q = (
    "Do you consent to Avdei Elohim Church Inc. collecting and using your "
    "personal information as described above?"
)
FACEBOOK_Q = (
    "May we greet you by name on the Avdei Elohim Church Inc. Facebook page "
    "for your birthday and wedding anniversary?"
)

HEADERS = [
    "Timestamp",
    CONSENT_Q,
    FACEBOOK_Q,
    "Last Name",
    "First Name",
    "Middle Name",
    "Suffix",
    "Nickname",
    "Date of Birth",
    "Place of Birth (e.g. Baguio City, La Trinidad)",
    "Sex",
    "Civil Status",
    "Nationality",
    "Home Address",
    "Mobile Number",
    "Email",
    "Spouse Name",
    "Date of Marriage",
    "Child 1 Name",
    "Child 1 Date of Birth",
    "Emergency Contact Name",
    "Emergency Contact Relationship",
    "Emergency Contact Number",
    "Committees you wish to be part of",
    "Anything else the Secretariat should know",
]


def response(timestamp="2026-08-24 09:15:22", consent="Yes, I consent.", **overrides):
    row = {
        "Timestamp": timestamp,
        CONSENT_Q: consent,
        FACEBOOK_Q: "Yes, you may post my name.",
        "Last Name": "Lardizabal",
        "First Name": "Marites",
        "Middle Name": "",
        "Suffix": "",
        "Nickname": "Tess",
        "Date of Birth": dt.datetime(1988, 4, 9),
        "Place of Birth (e.g. Baguio City, La Trinidad)": "La Trinidad",
        "Sex": "Female",
        "Civil Status": "Married",
        "Nationality": "",
        "Home Address": "7 Fictional Lane, La Trinidad",
        "Mobile Number": "09171112222",
        "Email": "tess@example.com",
        "Spouse Name": "",
        "Date of Marriage": "",
        "Child 1 Name": "",
        "Child 1 Date of Birth": "",
        "Emergency Contact Name": "",
        "Emergency Contact Relationship": "",
        "Emergency Contact Number": "",
        "Committees you wish to be part of": "Sunshine, Food",
        "Anything else the Secretariat should know": "",
    }
    row.update(overrides)
    return [row[header] for header in HEADERS]


def sheet(*rows):
    return [list(HEADERS), *rows]


def as_xlsx(*rows):
    workbook = openpyxl.Workbook()
    workbook.active.append(list(HEADERS))
    for row in rows:
        workbook.active.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# -- recognition -------------------------------------------------------


def test_a_response_sheet_is_recognised_by_its_timestamp_and_names():
    assert looks_like_response_sheet(HEADERS)


def test_the_ai_template_is_not_mistaken_for_one():
    from imports.spreadsheet import HEADER_TEXTS

    assert not looks_like_response_sheet(list(HEADER_TEXTS))


# -- mapping -----------------------------------------------------------


def test_a_response_becomes_an_entry_the_rest_of_the_import_understands():
    entry = parse_response_rows(sheet(response()))[0]

    assert entry["last_name"] == "Lardizabal"
    assert entry["first_name"] == "Marites"
    assert entry["nickname"] == "Tess"
    assert entry["gender"] == "FEMALE"
    assert entry["civil_status"] == "MARRIED"
    assert entry["mobile_number"] == "09171112222"


def test_a_question_whose_wording_drifted_still_matches():
    """The first real export already read "Place of Birth (e.g. Baguio
    City, La Trinidad)" -- the form gets edited and its headers move."""
    entry = parse_response_rows(sheet(response()))[0]

    assert entry["place_of_birth"] == "La Trinidad"


def test_dates_come_out_in_the_shape_the_importer_expects():
    entry = parse_response_rows(sheet(response()))[0]

    assert entry["date_of_birth"] == "1988-04-09"


def test_an_american_style_date_from_a_csv_export_is_converted():
    entry = parse_response_rows(sheet(response(**{"Date of Birth": "4/9/1988"})))[0]

    assert entry["date_of_birth"] == "1988-04-09"


def test_the_committee_checkbox_cell_becomes_a_list():
    entry = parse_response_rows(sheet(response()))[0]

    assert entry["committees"] == ["Sunshine", "Food"]


def test_a_committee_name_aegis_does_not_know_is_reported_not_dropped():
    with pytest.raises(ImportValidationError) as exc:
        parse_response_rows(
            sheet(response(**{"Committees you wish to be part of": "Sunshine, Choir"}))
        )

    assert any("Choir" in error for error in exc.value.errors)


def test_children_are_collected_into_the_shape_the_importer_uses():
    entry = parse_response_rows(
        sheet(
            response(
                **{
                    "Child 1 Name": "Bea Lardizabal",
                    "Child 1 Date of Birth": dt.datetime(2016, 2, 2),
                }
            )
        )
    )[0]

    assert entry["children"] == [
        {"full_name": "Bea Lardizabal", "date_of_birth": "2016-02-02"}
    ]


def test_an_online_response_is_v3_and_consented():
    entry = parse_response_rows(sheet(response()))[0]

    assert entry["form_version"] == "v3"
    assert entry["consent_given"] is True
    assert entry["confidence"] == "high"


def test_the_facebook_answer_is_carried_as_its_own_thing():
    yes = parse_response_rows(sheet(response()))[0]
    no = parse_response_rows(
        sheet(response(**{FACEBOOK_Q: "No, please do not post my name."}))
    )[0]

    assert yes["public_greeting_consent"] is True
    assert no["public_greeting_consent"] is False


def test_somebody_who_declined_consent_is_not_staged_at_all():
    """The form skips its own questions for them, so there is nothing to
    record -- and holding their name is the exact thing they declined."""
    with pytest.raises(ImportValidationError) as exc:
        parse_response_rows(sheet(response(consent="No, I do not consent.")))

    assert any("declined" in error for error in exc.value.errors)


def test_a_blank_row_is_skipped_rather_than_failing_the_file():
    entries = parse_response_rows(sheet(response(), [""] * len(HEADERS)))

    assert len(entries) == 1


# -- through the real entry point --------------------------------------


def test_an_xlsx_export_is_routed_without_the_volunteer_saying_so():
    entries = parse_import_file(as_xlsx(response()))

    assert entries[0]["first_name"] == "Marites"


# -- the running list --------------------------------------------------


def upload_url():
    return reverse("admin:imports_importbatch_upload")


def ict_user():
    user = User.objects.create_user("ict", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.ICT))
    return user


def upload(client, *rows):
    return client.post(
        upload_url(),
        {
            "file": io.BytesIO(as_xlsx(*rows)),
        },
        format="multipart",
        follow=True,
    )


@pytest.mark.django_db
def test_re_uploading_the_running_list_stages_only_what_is_new(client):
    """The whole point. The volunteer updates the same sheet and uploads it
    again; only the responses added since last time become rows to review."""
    client.force_login(ict_user())
    first = response(timestamp="2026-08-24 09:15:22")
    second = response(timestamp="2026-08-25 10:02:41", **{"First Name": "Nilda"})

    upload(client, first)
    assert StagedPerson.objects.count() == 1

    upload(client, first, second)

    assert StagedPerson.objects.count() == 2
    assert sorted(
        StagedPerson.objects.values_list("raw_data__first_name", flat=True)
    ) == ["Marites", "Nilda"]


@pytest.mark.django_db
def test_a_response_already_approved_does_not_come_back(client):
    client.force_login(ict_user())
    row = response()
    upload(client, row)
    StagedPerson.objects.update(status=StagedPersonStatus.APPROVED)

    upload(client, row)

    assert StagedPerson.objects.count() == 1


@pytest.mark.django_db
def test_a_response_already_rejected_does_not_come_back(client):
    """A rejected row is a decision, not an absence."""
    client.force_login(ict_user())
    row = response()
    upload(client, row)
    StagedPerson.objects.update(status=StagedPersonStatus.REJECTED)

    upload(client, row)

    assert StagedPerson.objects.count() == 1


@pytest.mark.django_db
def test_uploading_a_file_with_nothing_new_says_so_and_makes_no_batch(client):
    client.force_login(ict_user())
    row = response()
    upload(client, row)
    batches = ImportBatch.objects.count()

    result = upload(client, row)

    assert ImportBatch.objects.count() == batches
    assert "already been imported" in result.content.decode()


@pytest.mark.django_db
def test_the_submission_timestamp_is_what_identifies_a_response(client):
    client.force_login(ict_user())

    upload(client, response(timestamp="2026-08-24 09:15:22"))

    assert StagedPerson.objects.get().source_key == "2026-08-24 09:15:22"


# -- approval ----------------------------------------------------------


@pytest.mark.django_db
def test_approving_an_online_response_records_the_nickname_and_both_consents(ict_user_fixture=None):
    from imports.services import build_person_from_import

    user = User.objects.create_user("approver", password="x", is_staff=True)
    entry = parse_response_rows(sheet(response()))[0]
    entry["membership_status"] = MembershipStatus.MEMBER

    person, _ = build_person_from_import(entry, entry["children"], user)

    assert person.nickname == "Tess"
    assert person.consent_given is True
    assert person.consent_version == "v3"
    assert person.public_greeting_consent is True


@pytest.mark.django_db
def test_a_v2_paper_form_never_sets_the_facebook_consent():
    """v1 and v2 have no Facebook question, so their silence is not
    agreement -- the whole reason this is a separate opt-in field."""
    from imports.services import build_person_from_import

    user = User.objects.create_user("approver", password="x", is_staff=True)
    person, _ = build_person_from_import(
        {
            "last_name": "Lardizabal",
            "first_name": "Marites",
            "form_version": "v2",
            "certification_date": "2026-08-23",
            "public_greeting_consent": True,  # ignored: v2 never asked
            "membership_status": MembershipStatus.MEMBER,
        },
        [],
        user,
    )

    assert person.consent_version == "v2"
    assert person.public_greeting_consent is False
