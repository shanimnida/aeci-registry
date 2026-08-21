"""BUG (2026-08-22, empty households): imports/services.py used to create a
Household for every approved import row unconditionally, even a single
member with no spouse, no children and no date of marriage. Production
already holds these one-person households -- remove_empty_households cleans
them up.

All names below are fabricated. Real member data lives in `form images/` and
is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from people.models import Household, HouseholdMember, HouseholdRole, MembershipStatus, Person


@pytest.fixture
def lone_head_household(db):
    """A one-person household with no marriage date -- exactly what the
    empty-households bug wrote to production."""
    person = Person.objects.create(
        last_name="Ferrer", first_name="Noel",
        membership_status=MembershipStatus.MEMBER,
        home_address="",  # blank on the person, as the pre-fix households often left it
    )
    household = Household.objects.create(name="Ferrer Family", address="12 Fictional Rd, Baguio City")
    HouseholdMember.objects.create(household=household, person=person, role=HouseholdRole.HEAD)
    return household, person


@pytest.mark.django_db
def test_dry_run_reports_the_household_and_writes_nothing(lone_head_household):
    household, person = lone_head_household

    call_command("remove_empty_households", "--dry-run")

    # Proof it wrote nothing, not just an assertion of intent: reload from
    # the database and confirm every row is exactly as it was.
    assert Household.objects.filter(pk=household.pk).exists()
    assert HouseholdMember.objects.filter(household=household, person=person).exists()
    person.refresh_from_db()
    assert person.home_address == ""


@pytest.mark.django_db
def test_removes_a_one_person_household_with_no_marriage_date(lone_head_household):
    household, person = lone_head_household

    call_command("remove_empty_households")

    assert not Household.objects.filter(pk=household.pk).exists()
    assert not HouseholdMember.objects.filter(household=household).exists()
    # The person themself is untouched -- only the empty household is gone.
    assert Person.objects.filter(pk=person.pk).exists()


@pytest.mark.django_db
def test_moves_the_household_address_onto_the_person_before_deleting(lone_head_household):
    household, person = lone_head_household
    assert person.home_address == ""
    assert household.address == "12 Fictional Rd, Baguio City"

    call_command("remove_empty_households")

    person.refresh_from_db()
    assert person.home_address == "12 Fictional Rd, Baguio City"


@pytest.mark.django_db
def test_does_not_overwrite_an_existing_home_address_on_the_person(db):
    person = Person.objects.create(
        last_name="Torres", first_name="Aiza",
        membership_status=MembershipStatus.MEMBER,
        home_address="Person's Own Address, Baguio City",
    )
    household = Household.objects.create(name="Torres Family", address="Different Household Address")
    HouseholdMember.objects.create(household=household, person=person, role=HouseholdRole.HEAD)

    call_command("remove_empty_households")

    person.refresh_from_db()
    assert person.home_address == "Person's Own Address, Baguio City"


@pytest.mark.django_db
def test_refuses_a_household_with_two_members(db):
    head = Person.objects.create(last_name="Bautista", first_name="Rico", membership_status=MembershipStatus.MEMBER)
    spouse = Person.objects.create(last_name="Bautista", first_name="Grace", membership_status=MembershipStatus.MEMBER)
    household = Household.objects.create(name="Bautista Family")
    HouseholdMember.objects.create(household=household, person=head, role=HouseholdRole.HEAD)
    HouseholdMember.objects.create(household=household, person=spouse, role=HouseholdRole.SPOUSE)

    call_command("remove_empty_households")

    assert Household.objects.filter(pk=household.pk).exists()
    assert HouseholdMember.objects.filter(household=household).count() == 2


@pytest.mark.django_db
def test_refuses_a_household_with_a_date_of_marriage(db):
    person = Person.objects.create(last_name="Villanueva", first_name="Ken", membership_status=MembershipStatus.MEMBER)
    household = Household.objects.create(
        name="Villanueva Family", date_of_marriage=dt.date(2012, 6, 10)
    )
    HouseholdMember.objects.create(household=household, person=person, role=HouseholdRole.HEAD)

    call_command("remove_empty_households")

    assert Household.objects.filter(pk=household.pk).exists()


@pytest.mark.django_db
def test_refuses_a_household_whose_sole_member_is_not_head(db):
    person = Person.objects.create(last_name="Alonzo", first_name="Marife", membership_status=MembershipStatus.MEMBER)
    household = Household.objects.create(name="Alonzo Family")
    HouseholdMember.objects.create(household=household, person=person, role=HouseholdRole.OTHER)

    call_command("remove_empty_households")

    assert Household.objects.filter(pk=household.pk).exists()
    assert HouseholdMember.objects.filter(household=household, person=person, role=HouseholdRole.OTHER).exists()


@pytest.mark.django_db
def test_running_twice_removes_nothing_the_second_time(lone_head_household):
    household, person = lone_head_household

    first_count = call_command("remove_empty_households")
    assert first_count == "1"
    assert not Household.objects.filter(pk=household.pk).exists()

    second_count = call_command("remove_empty_households")
    assert second_count == "0"


@pytest.mark.django_db
def test_a_household_with_no_address_and_no_person_address_is_still_removed(db):
    """Nothing to move -- both are already blank -- must not block the
    removal itself."""
    person = Person.objects.create(last_name="Gomez", first_name="Ivy", membership_status=MembershipStatus.MEMBER)
    household = Household.objects.create(name="Gomez Family")
    HouseholdMember.objects.create(household=household, person=person, role=HouseholdRole.HEAD)

    call_command("remove_empty_households")

    assert not Household.objects.filter(pk=household.pk).exists()


@pytest.mark.django_db
def test_created_before_spares_a_household_made_after_the_cutoff(lone_head_household):
    """The fixed importer still makes a one-HEAD household with no marriage
    date for a form naming a spouse who is not in the register yet -- see
    tests/imports/test_household_creation.py. Nothing on the row tells that
    apart from the bug's output, so --created-before is how a re-run is
    scoped to households that predate the fix."""
    household, person = lone_head_household
    cutoff = timezone.localtime(household.created_at).date()

    call_command("remove_empty_households", "--created-before", cutoff.isoformat())

    # Created today, cutoff is today: created_at is not < local midnight.
    assert Household.objects.filter(pk=household.pk).exists()

    call_command(
        "remove_empty_households",
        "--created-before",
        (cutoff + dt.timedelta(days=1)).isoformat(),
    )
    assert not Household.objects.filter(pk=household.pk).exists()


@pytest.mark.django_db
def test_created_before_rejects_a_date_it_cannot_read(lone_head_household):
    household, _ = lone_head_household

    with pytest.raises(CommandError):
        call_command("remove_empty_households", "--created-before", "23-08-2026")

    assert Household.objects.filter(pk=household.pk).exists()
