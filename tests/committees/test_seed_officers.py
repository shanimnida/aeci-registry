import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from committees.models import CommitteeMembership, CommitteeRole
from people.models import MembershipStatus, Person

CSV = """last_name,first_name,nickname,membership_status,committee_code,role,start_date
Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON,2026-07-05
Reyes,Manex,,MEMBER,general-services,CHAIRPERSON,2026-07-05
Malong,Shan Albert,Shan,MEMBER,ict,CHAIRPERSON,2026-07-05
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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON,2026-07-05\n"
        "Cruz,Ana,,MEMBER,sunshine,CHAIRPERSON,2026-07-06\n"
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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,MEMBER,not-a-real-committee,CHAIRPERSON,2026-07-05\n"
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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON,not-a-date\n"
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
    csv_text = (
        "last_name,first_name,nickname,membership_status,committee_code,role\n"
        "Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON\n"
    )
    path = write_csv(tmp_path, csv_text)

    with pytest.raises(CommandError, match="missing column"):
        call_command("seed_officers", "--path", str(path))

    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_the_shipped_officers_csv_imports_cleanly():
    """data/officers.csv is the file the ICT Committee actually edits --
    prove the six known chairpersons import without any row failing, and
    that they land at MEMBER (per the CSV's membership_status column)
    rather than the RELATED default get_or_create() used to leave them at.
    """
    call_command("seed_officers", "--path", "data/officers.csv")
    assert Person.objects.count() == 6
    assert CommitteeMembership.objects.filter(role=CommitteeRole.CHAIRPERSON).count() == 6
    assert (
        Person.objects.filter(membership_status=MembershipStatus.MEMBER).count() == 6
    )
    # No approved_by was invented for any of them -- creating a record
    # already at MEMBER does not require one.
    assert not Person.objects.filter(approved_by__isnull=False).exists()


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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,MEMBER,ict,CHAIRPERSON,2026-07-05\n",
        name="original.csv",
    )
    call_command("seed_officers", "--path", str(original))

    moved = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,MEMBER,events,CHAIRPERSON,2026-07-06\n",
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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,,MEMBER,ict,CHAIRPERSON,2026-07-05\n",
        name="first.csv",
    )
    call_command("seed_officers", "--path", str(first_pass))
    person = Person.objects.get(last_name="Malong")
    assert person.nickname == ""

    corrected = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,MEMBER,ict,CHAIRPERSON,2026-07-05\n",
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
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,Shan,MEMBER,ict,CHAIRPERSON,2026-07-05\n",
        name="with_nickname.csv",
    )
    call_command("seed_officers", "--path", str(with_nickname))

    blank_nickname = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Malong,Shan Albert,,MEMBER,ict,CHAIRPERSON,2026-07-05\n",
        name="blank_nickname.csv",
    )
    call_command("seed_officers", "--path", str(blank_nickname))

    person = Person.objects.get(last_name="Malong")
    assert person.nickname == "Shan"


@pytest.mark.django_db
def test_a_second_self_selected_member_role_is_accepted_not_refused(tmp_path):
    """The moved-officer conflict check is scoped to CHAIRPERSON/CO_CHAIR
    only -- a second active MEMBER role on a different self-selectable
    committee is explicitly legal (the two-committee cap), so this
    command must let the row through rather than refusing it itself.
    """
    first = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Cruz,Ana,,MEMBER,ict,MEMBER,2026-07-05\n",
        name="first.csv",
    )
    call_command("seed_officers", "--path", str(first))

    second = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Cruz,Ana,,MEMBER,events,MEMBER,2026-07-06\n",
        name="second.csv",
    )
    call_command("seed_officers", "--path", str(second))

    memberships = CommitteeMembership.objects.filter(
        person__last_name="Cruz", role=CommitteeRole.MEMBER
    )
    assert memberships.count() == 2
    assert set(memberships.values_list("committee__code", flat=True)) == {
        "ict",
        "events",
    }


@pytest.mark.django_db
def test_a_third_self_selected_member_role_is_rejected_by_the_models_cap(
    tmp_path, capsys
):
    """A third MEMBER committee must still be refused -- but by
    CommitteeMembership.clean()'s own two-committee cap, not by this
    command's CHAIRPERSON/CO_CHAIR-only conflict check. Proven by checking
    which error text comes back: the cap's "up to two", not the command's
    "already holds an active" conflict message.
    """
    call_command(
        "seed_officers",
        "--path",
        str(
            write_csv(
                tmp_path,
                "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
                "Cruz,Ana,,MEMBER,ict,MEMBER,2026-07-05\n",
                name="first.csv",
            )
        ),
    )
    call_command(
        "seed_officers",
        "--path",
        str(
            write_csv(
                tmp_path,
                "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
                "Cruz,Ana,,MEMBER,events,MEMBER,2026-07-06\n",
                name="second.csv",
            )
        ),
    )

    third = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Cruz,Ana,,MEMBER,food,MEMBER,2026-07-07\n",
        name="third.csv",
    )
    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(third))
    assert "1 of 1 row(s) failed" in str(exc.value)

    stderr = capsys.readouterr().err
    assert "up to two" in stderr.lower()
    assert "already holds an active" not in stderr

    assert (
        CommitteeMembership.objects.filter(
            person__last_name="Cruz", role=CommitteeRole.MEMBER
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_a_new_officer_is_seeded_at_the_csv_stated_membership_status(tmp_path):
    """Gap 2: a brand-new officer must not be created at the RELATED
    default get_or_create() left them at -- the CSV states the true
    status (the ICT Committee's fact, sourced from Board minutes), and the
    command records it. Setting membership_status on a *new* instance
    needs no approved_by: Person.clean() only demands one when an existing
    record changes to MEMBER, and this row has no existing record to
    change.
    """
    path = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON,2026-07-05\n",
    )
    call_command("seed_officers", "--path", str(path))
    officer = Person.objects.get(last_name="Santos")
    assert officer.membership_status == MembershipStatus.MEMBER
    assert officer.approved_by is None


@pytest.mark.django_db
def test_a_blank_membership_status_is_rejected_not_defaulted(tmp_path, capsys):
    """A row that leaves membership_status blank must be refused, not
    silently defaulted -- neither to RELATED (which would misdescribe an
    actual chairperson, recreating the exact bug this fixes) nor to MEMBER
    (which would be the software deciding membership instead of recording
    a decision the ICT Committee made). The ICT Committee must state it.
    """
    path = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,,sunshine,CHAIRPERSON,2026-07-05\n",
    )
    with pytest.raises(CommandError) as exc:
        call_command("seed_officers", "--path", str(path))
    assert "1 of 1 row(s) failed" in str(exc.value)
    assert Person.objects.count() == 0

    stderr = capsys.readouterr().err
    assert "membership_status" in stderr.lower()


@pytest.mark.django_db
def test_an_existing_persons_membership_status_is_never_promoted_by_a_rerun(tmp_path):
    """Must not silently promote anyone to membership: once a person
    exists on file, a later CSV row naming a different membership_status
    is not applied to them. Only an explicit admin edit -- which
    Person.clean() gates on approved_by -- may change an existing person's
    recorded status.
    """
    first_pass = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,RELATED,sunshine,CHAIRPERSON,2026-07-05\n",
        name="first.csv",
    )
    call_command("seed_officers", "--path", str(first_pass))
    officer = Person.objects.get(last_name="Santos")
    assert officer.membership_status == MembershipStatus.RELATED

    second_pass = write_csv(
        tmp_path,
        "last_name,first_name,nickname,membership_status,committee_code,role,start_date\n"
        "Santos,Rhea,,MEMBER,sunshine,CHAIRPERSON,2026-07-05\n",
        name="second.csv",
    )
    call_command("seed_officers", "--path", str(second_pass))

    officer.refresh_from_db()
    assert officer.membership_status == MembershipStatus.RELATED
