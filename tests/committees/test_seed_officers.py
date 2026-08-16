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
