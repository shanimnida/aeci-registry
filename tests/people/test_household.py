import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

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


@pytest.mark.django_db
def test_a_future_date_of_marriage_is_refused():
    """IMPORTANT 4."""
    household = Household(
        name="Malong Family", date_of_marriage=timezone.localdate() + dt.timedelta(days=1)
    )
    with pytest.raises(ValidationError) as exc:
        household.full_clean()
    assert "date_of_marriage" in exc.value.message_dict


@pytest.mark.django_db
def test_a_marriage_date_before_the_head_own_birth_date_is_refused():
    """IMPORTANT 4: a marriage cannot predate the person who entered it."""
    household = Household.objects.create(name="Malong Family", date_of_marriage=dt.date(1990, 1, 1))
    head = Person.objects.create(last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 3, 2))
    member = HouseholdMember(household=household, person=head, role=HouseholdRole.HEAD)
    with pytest.raises(ValidationError) as exc:
        member.full_clean()
    assert "household" in exc.value.message_dict


@pytest.mark.django_db
def test_a_marriage_date_after_both_spouses_birth_dates_is_accepted():
    household = Household.objects.create(name="Malong Family", date_of_marriage=dt.date(2015, 6, 1))
    head = Person.objects.create(last_name="Malong", first_name="Shan", date_of_birth=dt.date(1990, 1, 1))
    member = HouseholdMember(household=household, person=head, role=HouseholdRole.HEAD)
    member.full_clean()
    member.save()
    assert member.pk is not None


@pytest.mark.django_db
def test_a_child_older_than_the_household_head_is_refused():
    """IMPORTANT 4."""
    household = Household.objects.create(name="Malong Family")
    head = Person.objects.create(last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 1, 1))
    HouseholdMember.objects.create(household=household, person=head, role=HouseholdRole.HEAD)
    older_child = Person.objects.create(
        last_name="Malong", first_name="Elder", date_of_birth=dt.date(1980, 1, 1)
    )
    member = HouseholdMember(household=household, person=older_child, role=HouseholdRole.CHILD)
    with pytest.raises(ValidationError) as exc:
        member.full_clean()
    assert "person" in exc.value.message_dict


@pytest.mark.django_db
def test_a_child_younger_than_the_household_head_is_accepted():
    household = Household.objects.create(name="Malong Family")
    head = Person.objects.create(last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 1, 1))
    HouseholdMember.objects.create(household=household, person=head, role=HouseholdRole.HEAD)
    child = Person.objects.create(
        last_name="Malong", first_name="Junior", date_of_birth=dt.date(2020, 1, 1)
    )
    member = HouseholdMember(household=household, person=child, role=HouseholdRole.CHILD)
    member.full_clean()
    member.save()
    assert member.pk is not None


@pytest.mark.django_db
def test_a_child_with_no_recorded_birth_date_is_not_refused():
    """IMPORTANT 4's own constraint: prefer refusing the impossible over the
    improbable. A blank date of birth cannot be compared, so it must not be
    treated as a failure -- the paper backlog often has no birth date at all."""
    household = Household.objects.create(name="Malong Family")
    head = Person.objects.create(last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 1, 1))
    HouseholdMember.objects.create(household=household, person=head, role=HouseholdRole.HEAD)
    child = Person.objects.create(last_name="Malong", first_name="Unknown")
    member = HouseholdMember(household=household, person=child, role=HouseholdRole.CHILD)
    member.full_clean()
    member.save()
    assert member.pk is not None
