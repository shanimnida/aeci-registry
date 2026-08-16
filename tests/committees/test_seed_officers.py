import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from committees.models import CommitteeMembership, CommitteeRole
from people.models import Person

CSV = """last_name,first_name,nickname,committee_code,role,start_date
Santos,Rhea,,sunshine,CHAIRPERSON,2026-07-05
Reyes,Manex,,general-services,CHAIRPERSON,2026-07-05
Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05
"""


def write_csv(tmp_path, text, name="officers.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def officers_csv(tmp_path):
    return write_csv(tmp_path, CSV)


@pytest.mark.django_db
def test_officers_are_created_with_their_committees(officers_csv):
    call_command("seed_officers", "--path", str(officers_csv))
    assert Person.objects.count() == 3
    shan = Person.objects.get(last_name="Malong")
    assert shan.nickname == "Shan"
    membership = CommitteeMembership.objects.get(person=shan)
    assert membership.committee.code == "ict"
    assert membership.role == CommitteeRole.CHAIRPERSON


@pytest.mark.django_db
def test_running_it_twice_creates_no_duplicates(officers_csv):
    call_command("seed_officers", "--path", str(officers_csv))
    call_command("seed_officers", "--path", str(officers_csv))
    assert Person.objects.count() == 3
    assert CommitteeMembership.objects.count() == 3


@pytest.mark.django_db
def test_missing_path_is_a_clear_command_error(tmp_path):
    missing = tmp_path / "nope.csv"
    with pytest.raises(CommandError, match="not found"):
        call_command("seed_officers", "--path", str(missing))


@pytest.mark.django_db
def test_a_business_rule_violation_is_reported_and_the_run_exits_non_zero(tmp_path, capsys):
    """A second Chairperson for a committee that already has one must be
    caught by CommitteeMembership.full_clean() (the single-chairperson
    rule), reported by row, and must not silently succeed.
    """
    csv_text = (
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Santos,Rhea,,sunshine,CHAIRPERSON,2026-07-05\n"
        "Cruz,Ana,,sunshine,CHAIRPERSON,2026-07-06\n"
    )
    path = write_csv(tmp_path, csv_text)

    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(path))

    assert "1 of 2 row(s) failed" in str(exc.value)

    # The first, valid row still imported -- one bad row does not abort
    # rows that already passed.
    assert Person.objects.filter(last_name="Santos").exists()
    assert CommitteeMembership.objects.filter(
        person__last_name="Santos", committee__code="sunshine"
    ).exists()

    # The clashing row was not applied at all -- not the person, not the
    # membership -- so re-running after a fix won't find a half-saved row.
    assert not Person.objects.filter(last_name="Cruz").exists()

    stderr = capsys.readouterr().err
    assert "Row 3" in stderr
    assert "chairperson" in stderr.lower()


@pytest.mark.django_db
def test_an_unknown_committee_code_is_reported_by_row_not_a_traceback(tmp_path):
    csv_text = (
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Santos,Rhea,,not-a-real-committee,CHAIRPERSON,2026-07-05\n"
    )
    path = write_csv(tmp_path, csv_text)

    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(path))

    assert "1 of 1 row(s) failed" in str(exc.value)
    assert Person.objects.count() == 0
    assert CommitteeMembership.objects.count() == 0


@pytest.mark.django_db
def test_a_malformed_date_is_reported_by_row_not_a_traceback(tmp_path):
    csv_text = (
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Santos,Rhea,,sunshine,CHAIRPERSON,not-a-date\n"
    )
    path = write_csv(tmp_path, csv_text)

    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(path))

    assert "1 of 1 row(s) failed" in str(exc.value)
    # The Person was rolled back along with the failed membership row --
    # the row is all-or-nothing.
    assert Person.objects.count() == 0
    assert CommitteeMembership.objects.count() == 0


@pytest.mark.django_db
def test_a_missing_csv_column_fails_fast_before_writing_anything(tmp_path):
    csv_text = "last_name,first_name,nickname,committee_code,role\nSantos,Rhea,,sunshine,CHAIRPERSON\n"
    path = write_csv(tmp_path, csv_text)

    with pytest.raises(CommandError, match="missing column"):
        call_command("seed_officers", "--path", str(path))

    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_the_shipped_officers_csv_imports_cleanly():
    """data/officers.csv is the file the ICT Committee actually edits --
    prove the six known chairpersons import without any row failing.
    """
    call_command("seed_officers", "--path", "data/officers.csv")
    assert Person.objects.count() == 6
    assert CommitteeMembership.objects.filter(role=CommitteeRole.CHAIRPERSON).count() == 6


@pytest.mark.django_db
def test_a_bom_prefixed_csv_from_excel_imports_cleanly(tmp_path):
    """Excel's "CSV UTF-8" export writes a byte-order mark. Opened as plain
    utf-8 that turns the header's first column into '﻿last_name',
    which used to make a genuinely present column look missing.
    """
    path = tmp_path / "officers_from_excel.csv"
    path.write_text(CSV, encoding="utf-8-sig")

    call_command("seed_officers", "--path", str(path))

    assert Person.objects.count() == 3
    assert CommitteeMembership.objects.count() == 3


@pytest.mark.django_db
def test_moving_an_officer_to_a_new_committee_is_refused_not_duplicated(tmp_path, capsys):
    """Editing committee_code on an existing officer's row must not create
    a second active membership in the same role -- that would leave them
    Chairperson of two committees at once with nothing rejecting it,
    because the single-chairperson rule guards the committee, not the
    person. The command must refuse instead of guessing that the old
    membership should be closed.
    """
    original = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05\n",
        name="original.csv",
    )
    call_command("seed_officers", "--path", str(original))

    moved = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,events,CHAIRPERSON,2026-07-06\n",
        name="moved.csv",
    )

    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(moved))
    assert "1 of 1 row(s) failed" in str(exc.value)

    # Still only the original ICT membership -- no second active
    # Chairperson row was created on Events.
    memberships = CommitteeMembership.objects.filter(person__last_name="Malong")
    assert memberships.count() == 1
    assert memberships.get().committee.code == "ict"

    stderr = capsys.readouterr().err
    assert "Row 2" in stderr
    assert "ICT" in stderr
    assert "Events" in stderr


@pytest.mark.django_db
def test_a_nickname_correction_on_a_rerun_updates_the_person(tmp_path, capsys):
    """The CSV exists so that a nickname-only officer can be resolved to a
    full name over time. Editing the nickname column and re-running must
    actually apply the correction, not silently do nothing.
    """
    first_pass = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,,ict,CHAIRPERSON,2026-07-05\n",
        name="first.csv",
    )
    call_command("seed_officers", "--path", str(first_pass))
    person = Person.objects.get(last_name="Malong")
    assert person.nickname == ""

    corrected = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05\n",
        name="corrected.csv",
    )
    call_command("seed_officers", "--path", str(corrected))

    person.refresh_from_db()
    assert person.nickname == "Shan"

    stdout = capsys.readouterr().out
    assert "nickname" in stdout.lower()
    assert "Shan" in stdout

    # Idempotent: running the identical corrected CSV again does not
    # create a duplicate person or membership, and reports no further
    # nickname change.
    call_command("seed_officers", "--path", str(corrected))
    assert Person.objects.count() == 1
    assert CommitteeMembership.objects.count() == 1


@pytest.mark.django_db
def test_a_blank_csv_nickname_does_not_erase_an_existing_one(tmp_path):
    """Absence of a nickname in the CSV is not an instruction to erase a
    previously resolved one -- a spreadsheet row left blank should not
    regress data that was already fixed.
    """
    with_nickname = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05\n",
        name="with_nickname.csv",
    )
    call_command("seed_officers", "--path", str(with_nickname))

    blank_nickname = write_csv(
        tmp_path,
        "last_name,first_name,nickname,committee_code,role,start_date\n"
        "Malong,Shan Albert,,ict,CHAIRPERSON,2026-07-05\n",
        name="blank_nickname.csv",
    )
    call_command("seed_officers", "--path", str(blank_nickname))

    person = Person.objects.get(last_name="Malong")
    assert person.nickname == "Shan"
