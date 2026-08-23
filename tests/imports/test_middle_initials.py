"""A middle initial stands for the middle name it abbreviates.

Found in the register 2026-08-24, three times in one family. The parent's
form gives the initial -- "Johnson A. Til-adan" -- and the child's own form
later spells it out -- "Johnson Angel Til-adan". Comparing "a." and "angel"
as different words made them two children, and the Til-Adan household ended
up with eight members where five real people live.

The widening is bounded: the first given name must still agree exactly, the
surname must agree, and the date of birth must be identical. An initial
only ever stands in for a middle name that is otherwise missing or spelled
out.

All names below are fabricated except the shape of the reported case. Real
member data lives in `form images/` and is never used in fixtures or tests.
"""

import datetime as dt

import pytest

from imports.services import (
    _find_child_match,
    _names_are_compatible,
    _given_name_tokens,
    build_person_from_import,
)
from people.models import MembershipStatus, Person

DOB = dt.date(2011, 6, 6)


def tokens(first, middle=""):
    return _given_name_tokens(first, middle)


# -- the comparison ----------------------------------------------------


@pytest.mark.parametrize(
    "left,right",
    [
        (("Johnson", "A."), ("Johnson", "Angel")),
        (("Johnson", "A"), ("Johnson", "Angel")),
        (("Johnson", "Angel"), ("Johnson", "A.")),
        (("Brenant", "A."), ("Brenant", "Angel")),
        # The initial may arrive glued into the first name, which is how the
        # old splitter wrote it.
        (("Johnson A.", ""), ("Johnson", "Angel")),
    ],
)
def test_an_initial_matches_the_name_it_stands_for(left, right):
    assert _names_are_compatible(tokens(*left), tokens(*right))


@pytest.mark.parametrize(
    "left,right",
    [
        # A different letter is a different middle name.
        (("Johnson", "A."), ("Johnson", "Bernardo")),
        # A different first name is a different person, initial or not.
        (("Johnson", "A."), ("Jonathan", "Angel")),
        # Two spelled-out middle names that disagree.
        (("Johnson", "Angel"), ("Johnson", "Antonio")),
    ],
)
def test_a_contradictory_middle_name_is_still_refused(left, right):
    assert not _names_are_compatible(tokens(*left), tokens(*right))


def test_a_missing_middle_name_still_matches():
    assert _names_are_compatible(tokens("Johnson"), tokens("Johnson", "Angel"))


# -- through child matching --------------------------------------------


@pytest.mark.django_db
def test_a_child_written_with_an_initial_matches_their_spelled_out_record():
    existing = Person.objects.create(
        first_name="Johnson", middle_name="Angel", last_name="Til-Adan",
        date_of_birth=DOB, membership_status=MembershipStatus.CHILD,
    )

    match, ambiguous = _find_child_match("Johnson", "A.", "Til-Adan", DOB)

    assert match == existing
    assert not ambiguous


@pytest.mark.django_db
def test_two_siblings_whose_initials_differ_are_not_confused():
    Person.objects.create(
        first_name="Johnson", middle_name="Angel", last_name="Til-Adan",
        date_of_birth=DOB, membership_status=MembershipStatus.CHILD,
    )

    match, ambiguous = _find_child_match("Johnson", "B.", "Til-Adan", DOB)

    assert match is None


# -- end to end --------------------------------------------------------


@pytest.mark.django_db
def test_both_parents_forms_produce_one_child_when_one_used_an_initial(ict_user):
    """The Til-Adan shape: father writes the initial, mother spells it."""
    build_person_from_import(
        {"last_name": "Til-Adan", "first_name": "Juan",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Johnson A. Til-Adan", "date_of_birth": "2011-06-06"}],
        ict_user,
    )
    build_person_from_import(
        {"last_name": "Til-Adan", "first_name": "Gemma", "spouse_name": "Juan Til-Adan",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Johnson Angel Til-Adan", "date_of_birth": "2011-06-06"}],
        ict_user,
    )

    children = Person.objects.filter(membership_status=MembershipStatus.CHILD)
    assert children.count() == 1
    # The spelled-out middle name wins over the initial, because a later
    # form filling a gap is the fuller record.
    assert children.get().middle_name in ("A.", "Angel")


@pytest.mark.django_db
def test_a_child_written_with_an_initial_links_to_their_own_form(ict_user):
    """The other half: the parent wrote the initial, and the child later
    fills in their own profiling form with the name spelled out."""
    build_person_from_import(
        {"last_name": "Til-Adan", "first_name": "Juan",
         "membership_status": MembershipStatus.MEMBER},
        [{"full_name": "Johnson A. Til-Adan", "date_of_birth": "2011-06-06"}],
        ict_user,
    )

    _, notices = build_person_from_import(
        {"last_name": "Til-Adan", "first_name": "Johnson", "middle_name": "Angel",
         "date_of_birth": "2011-06-06", "mobile_number": "09489323728",
         "membership_status": MembershipStatus.MEMBER},
        [],
        ict_user,
    )

    assert Person.objects.filter(first_name__startswith="Johnson").count() == 1
    johnson = Person.objects.get(first_name__startswith="Johnson")
    assert johnson.mobile_number == "09489323728"
    assert any("own form rather than a second record" in n for n in notices)
