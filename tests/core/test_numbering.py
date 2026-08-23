"""Member numbers went random on 2026-08-24.

They used to be sequential, which meant the number itself disclosed the
church's headcount and each member's place in the joining order -- fine on
an internal form, not fine on a card a member carries (spec 7.5). They are
now MEM- plus six random digits and a seventh check digit.

The check digit is the part worth testing hardest. It is what makes a
mistyped number fail instead of silently matching a different member, and
it is the definition `renumber_members` uses to tell a real number from one
it should replace.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import pytest
from django.core.management import call_command

from core.numbering import (
    MEMBER_NO_RE,
    damm_check_digit,
    damm_is_valid,
    member_no_is_valid,
    new_member_no,
    next_document_no,
)
from people.models import MembershipStatus, Person


# -- the check digit ----------------------------------------------------


def test_a_number_with_its_check_digit_validates():
    assert damm_is_valid("000001" + damm_check_digit("000001"))


def test_every_single_digit_error_is_caught():
    """The whole point. One wrong digit must never produce a number that
    looks real -- it would silently be a different member."""
    body = "483920"
    number = body + damm_check_digit(body)

    undetected = [
        number[:position] + digit + number[position + 1 :]
        for position in range(len(number))
        for digit in "0123456789"
        if digit != number[position]
        and damm_is_valid(number[:position] + digit + number[position + 1 :])
    ]

    assert undetected == []


def test_every_adjacent_transposition_is_caught():
    """Why Damm rather than Luhn: Luhn misses 09 <-> 90, and swapping two
    digits is the error a human makes copying a number off a card."""
    body = "483920"
    number = body + damm_check_digit(body)

    undetected = [
        number[:position] + number[position + 1] + number[position] + number[position + 2 :]
        for position in range(len(number) - 1)
        if number[position] != number[position + 1]
        and damm_is_valid(
            number[:position]
            + number[position + 1]
            + number[position]
            + number[position + 2 :]
        )
    ]

    assert undetected == []


# -- the shape ----------------------------------------------------------


@pytest.mark.django_db
def test_a_new_number_has_the_prefix_seven_digits_and_a_good_check_digit():
    number = new_member_no()

    assert MEMBER_NO_RE.match(number)
    assert member_no_is_valid(number)


@pytest.mark.django_db
def test_numbers_are_not_sequential():
    """If they came out in order the change would have achieved nothing."""
    numbers = [new_member_no() for _ in range(12)]

    suffixes = [int(MEMBER_NO_RE.match(n).group(1)) for n in numbers]
    assert suffixes != sorted(suffixes)
    assert len(set(numbers)) == len(numbers)


@pytest.mark.django_db
def test_a_number_already_on_file_is_never_issued_twice(monkeypatch):
    taken = new_member_no()
    Person.objects.create(last_name="Awingan", first_name="Del", member_no=taken)

    # Force the generator to offer the taken number first, then a fresh one.
    from core import numbering

    offers = iter([taken, taken, "MEM-9999990"])
    monkeypatch.setattr(numbering, "_candidate_member_no", lambda: next(offers))

    assert new_member_no() == "MEM-9999990"


@pytest.mark.django_db
def test_running_out_of_attempts_raises_rather_than_returning_a_duplicate(monkeypatch):
    """A loud failure beats handing out a number somebody already holds."""
    from core import numbering

    taken = new_member_no()
    Person.objects.create(last_name="Awingan", first_name="Del", member_no=taken)
    monkeypatch.setattr(numbering, "_candidate_member_no", lambda: taken)

    with pytest.raises(RuntimeError):
        numbering.new_member_no(max_attempts=3)


# -- validity -----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", None, "MEM-", "MEM-0001", "0000013", "MEM-000001", "MEM-00000134", "MEM-ABCDEFG"],
)
def test_malformed_numbers_are_not_valid(value):
    assert not member_no_is_valid(value)


def test_a_wrong_check_digit_is_not_valid():
    body = "483920"
    wrong = str((int(damm_check_digit(body)) + 1) % 10)

    assert not member_no_is_valid(f"MEM-{body}{wrong}")


# -- renumbering --------------------------------------------------------


@pytest.fixture
def old_style_members(db):
    return [
        Person.objects.create(
            last_name="Awingan",
            first_name=f"Member{index}",
            member_no=f"MEM-{index:04d}",
            membership_status=MembershipStatus.MEMBER,
        )
        for index in range(1, 4)
    ]


@pytest.mark.django_db
def test_dry_run_changes_nothing(old_style_members):
    call_command("renumber_members", "--dry-run")

    for person in old_style_members:
        before = person.member_no
        person.refresh_from_db()
        assert person.member_no == before


@pytest.mark.django_db
def test_old_sequential_numbers_are_replaced(old_style_members):
    call_command("renumber_members")

    for person in old_style_members:
        person.refresh_from_db()
        assert member_no_is_valid(person.member_no)
    assert len({p.member_no for p in Person.objects.all()}) == len(old_style_members)


@pytest.mark.django_db
def test_a_second_run_changes_nothing(old_style_members):
    """What makes the command safe to run twice: a number that already
    passes the check-digit test is left alone."""
    call_command("renumber_members")
    after_first = {p.pk: p.member_no for p in Person.objects.all()}

    call_command("renumber_members")

    assert {p.pk: p.member_no for p in Person.objects.all()} == after_first


@pytest.mark.django_db
def test_a_hand_set_number_with_a_good_check_digit_survives(db):
    """MEM-0000013 -- the check digit for 000001 is 3. Somebody who wants a
    particular number keeps it, provided they got the check digit right."""
    person = Person.objects.create(
        last_name="Malong", first_name="Shan", member_no="MEM-0000013"
    )

    call_command("renumber_members")

    person.refresh_from_db()
    assert person.member_no == "MEM-0000013"


@pytest.mark.django_db
def test_a_person_with_no_number_is_not_given_one(db):
    """D9: issuing a number to somebody the church never accepted leaves a
    permanent gap in the register. Renumbering is not the place to do it."""
    person = Person.objects.create(last_name="Awingan", first_name="Nonumber")

    call_command("renumber_members")

    person.refresh_from_db()
    assert person.member_no is None


# -- document numbers are unchanged -------------------------------------


@pytest.mark.django_db
def test_document_numbers_are_still_sequential_and_per_year():
    """Phase B's numbers are filed and reported by year, so they stay in
    order -- this change was about identity, not about every number."""
    assert next_document_no("EARF", 2026) == "EARF-2026-001"
    assert next_document_no("EARF", 2026) == "EARF-2026-002"
    assert next_document_no("EARF", 2027) == "EARF-2027-001"
    assert next_document_no("FR", 2026) == "FR-2026-001"
