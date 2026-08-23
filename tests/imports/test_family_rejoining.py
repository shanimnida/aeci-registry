"""Two fixes from real data, 2026-08-24.

**Duplicate households (the Reyes case).** A form that leaves Spouse Name
blank used to get its own household even when the children it lists were
already recorded in the other parent's. Both parents' forms list the same
children -- that is how the paper form works, and it is the premise the
child-linking was built on -- so those children ARE the evidence that two
rows are one family.

**A child's own form.** Parents write a given name and nothing else --
"Rhyzel", no middle name, no surname -- so AEGIS records her with the
parent's surname. Years later she fills in her own form as "Rhyzel Bayatin
Reyes" and got a second Person row, because the rule was that the subject
of a form is always somebody new. Right for adults, wrong for the one case
where AEGIS made the earlier record itself.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest

from imports.services import build_person_from_import
from people.models import Household, HouseholdRole, MembershipStatus, Person

ANA = [{"full_name": "Ana", "date_of_birth": "2014-01-01"}]
BEA = [{"full_name": "Bea", "date_of_birth": "2016-02-02"}]


def parent(first_name, children, **extra):
    data = {
        "last_name": "Reyes",
        "first_name": first_name,
        "membership_status": MembershipStatus.MEMBER,
    }
    data.update(extra)
    return data, children


# -- one family, one household -----------------------------------------


@pytest.mark.django_db
def test_a_form_with_no_spouse_name_joins_the_household_its_children_are_in(ict_user):
    """The Reyes case exactly. Neither form has to name the spouse; the
    children do the work."""
    data, kids = parent("Juan", ANA, spouse_name="Maria Reyes")
    build_person_from_import(data, kids, ict_user)

    data, kids = parent("Maria", ANA)  # no spouse_name at all
    _, notices = build_person_from_import(data, kids, ict_user)

    assert Household.objects.count() == 1
    assert Household.objects.get().members.count() == 3
    assert any("rather than starting a second one" in n for n in notices)


@pytest.mark.django_db
def test_the_second_parent_joins_as_spouse_not_as_a_second_head(ict_user):
    data, kids = parent("Juan", ANA, spouse_name="Maria Reyes")
    build_person_from_import(data, kids, ict_user)

    data, kids = parent("Maria", ANA)
    maria, _ = build_person_from_import(data, kids, ict_user)

    assert Household.objects.get().members.get(person=maria).role == HouseholdRole.SPOUSE


@pytest.mark.django_db
def test_the_child_is_not_added_to_the_household_twice(ict_user):
    data, kids = parent("Juan", ANA, spouse_name="Maria Reyes")
    build_person_from_import(data, kids, ict_user)
    data, kids = parent("Maria", ANA)
    build_person_from_import(data, kids, ict_user)

    child = Person.objects.get(membership_status=MembershipStatus.CHILD)
    assert child.household_memberships.count() == 1


@pytest.mark.django_db
def test_a_marriage_date_on_the_second_form_reaches_the_joined_household(ict_user):
    data, kids = parent("Juan", ANA, spouse_name="Maria Reyes")
    build_person_from_import(data, kids, ict_user)

    data, kids = parent("Maria", ANA, date_of_marriage="2011-05-05")
    build_person_from_import(data, kids, ict_user)

    assert Household.objects.get().date_of_marriage == dt.date(2011, 5, 5)


@pytest.mark.django_db
def test_an_unrelated_family_with_the_same_surname_gets_its_own_household(ict_user):
    """Joining is driven by the CHILDREN, not by the surname. Two Reyes
    families sharing no children stay two families."""
    data, kids = parent("Juan", ANA, spouse_name="Maria Reyes")
    build_person_from_import(data, kids, ict_user)

    data, kids = parent("Pedro", BEA)
    build_person_from_import(data, kids, ict_user)

    assert Household.objects.count() == 2


@pytest.mark.django_db
def test_children_spread_across_two_households_are_reported_not_guessed_at(ict_user):
    """A mess a human should look at, rather than one AEGIS picks a winner
    from."""
    data, kids = parent("Juan", ANA, spouse_name="X Reyes")
    build_person_from_import(data, kids, ict_user)
    data, kids = parent("Pedro", BEA, spouse_name="Y Reyes")
    build_person_from_import(data, kids, ict_user)
    before = Household.objects.count()

    data, kids = parent("Maria", ANA + BEA)
    _, notices = build_person_from_import(data, kids, ict_user)

    assert any("more than one household" in n for n in notices)
    # No third household: that would put each of these children in two, which
    # is worse than the tangle already there. The person is still recorded.
    assert Household.objects.count() == before
    assert Person.objects.filter(first_name="Maria").exists()


# -- a child's own form ------------------------------------------------


RHYZEL_AS_A_CHILD = [{"full_name": "Rhyzel", "date_of_birth": "2008-03-03"}]


def own_form(first_name, **extra):
    data = {
        "last_name": "Reyes",
        "first_name": first_name,
        "date_of_birth": "2008-03-03",
        "membership_status": MembershipStatus.MEMBER,
    }
    data.update(extra)
    return data


@pytest.mark.django_db
def test_a_child_filling_their_own_form_updates_their_record(ict_user):
    """The parent wrote "Rhyzel" and nothing else. Her own form carries the
    middle name and everything else."""
    data, kids = parent("Juan", RHYZEL_AS_A_CHILD)
    build_person_from_import(data, kids, ict_user)
    assert Person.objects.filter(first_name="Rhyzel").count() == 1

    _, notices = build_person_from_import(
        own_form("Rhyzel", middle_name="Bayatin", mobile_number="09171234567"),
        [],
        ict_user,
    )

    assert Person.objects.filter(first_name="Rhyzel").count() == 1
    rhyzel = Person.objects.get(first_name="Rhyzel")
    assert rhyzel.middle_name == "Bayatin"
    assert rhyzel.mobile_number == "09171234567"
    assert any("own form rather than a second record" in n for n in notices)


@pytest.mark.django_db
def test_her_own_form_does_not_erase_what_is_already_on_file(ict_user):
    """A blank on this form means "not answered", not "delete what you
    have"."""
    data, kids = parent("Juan", RHYZEL_AS_A_CHILD)
    build_person_from_import(data, kids, ict_user)
    rhyzel = Person.objects.get(first_name="Rhyzel")
    rhyzel.mobile_number = "09990000000"
    rhyzel.save()

    build_person_from_import(own_form("Rhyzel", middle_name="Bayatin"), [], ict_user)

    rhyzel.refresh_from_db()
    assert rhyzel.mobile_number == "09990000000"


@pytest.mark.django_db
def test_membership_is_left_alone_because_it_needs_a_named_approver(ict_user):
    """D15: changing somebody to MEMBER requires an approver, and a child
    growing up is exactly the decision that rule keeps attributable.
    Linking the record is identity; accepting them is a separate act."""
    data, kids = parent("Juan", RHYZEL_AS_A_CHILD)
    build_person_from_import(data, kids, ict_user)

    _, notices = build_person_from_import(
        own_form("Rhyzel", middle_name="Bayatin"), [], ict_user
    )

    assert Person.objects.get(first_name="Rhyzel").membership_status == (
        MembershipStatus.CHILD
    )
    assert any("named approver" in n for n in notices)


@pytest.mark.django_db
def test_an_adult_with_the_same_name_is_still_a_new_person(ict_user):
    """The match only ever looks at records AEGIS made from somebody else's
    form -- one with a guardian, or one still marked CHILD. Two unrelated
    adults sharing a name and a birthday stay two people."""
    build_person_from_import(own_form("Rhyzel", middle_name="Bayatin"), [], ict_user)

    build_person_from_import(own_form("Rhyzel", middle_name="Bayatin"), [], ict_user)

    assert Person.objects.filter(first_name="Rhyzel").count() == 2


@pytest.mark.django_db
def test_without_a_birthdate_on_the_form_nothing_is_linked(ict_user):
    """Nothing holds the match up without one, so it creates rather than
    guesses."""
    data, kids = parent("Juan", RHYZEL_AS_A_CHILD)
    build_person_from_import(data, kids, ict_user)

    data = own_form("Rhyzel")
    data.pop("date_of_birth")
    build_person_from_import(data, [], ict_user)

    assert Person.objects.filter(first_name="Rhyzel").count() == 2
