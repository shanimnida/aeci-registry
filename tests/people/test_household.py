import pytest
from django.db import IntegrityError

from people.models import Household, HouseholdMember, HouseholdRole, Person


@pytest.mark.django_db
def test_a_household_holds_a_spouse_and_children():
    household = Household.objects.create(
        name="Malong Family", date_of_marriage="2010-05-14"
    )
    head = Person.objects.create(last_name="Malong", first_name="Shan")
    spouse = Person.objects.create(last_name="Malong", first_name="Maria")
    child = Person.objects.create(last_name="Malong", first_name="Joy")

    HouseholdMember.objects.create(
        household=household, person=head, role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=household, person=spouse, role=HouseholdRole.SPOUSE
    )
    HouseholdMember.objects.create(
        household=household, person=child, role=HouseholdRole.CHILD
    )

    assert household.members.count() == 3
    assert household.members.filter(role=HouseholdRole.CHILD).count() == 1


@pytest.mark.django_db
def test_a_person_appears_once_per_household():
    household = Household.objects.create(name="Reyes Family")
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )
    with pytest.raises(IntegrityError):
        HouseholdMember.objects.create(
            household=household, person=person, role=HouseholdRole.OTHER
        )


@pytest.mark.django_db
def test_a_guardian_can_live_outside_the_household():
    """Spec section 3.2: a grandmother brings a child whose parents do not attend."""
    grandmother = Person.objects.create(last_name="Lang-ayan", first_name="Diana")
    child = Person.objects.create(
        last_name="Bilango",
        first_name="Ken",
        guardian=grandmother,
        guardian_relationship="Grandmother",
    )
    assert child.guardian == grandmother
    assert grandmother.wards.count() == 1
