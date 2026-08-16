import pytest
from django.core.exceptions import ValidationError

from people.models import MembershipStatus, Person


@pytest.mark.django_db
def test_only_names_are_required():
    person = Person(last_name="Malong", first_name="Shan")
    person.full_clean()
    person.save()
    assert person.pk is not None
    assert person.membership_status == MembershipStatus.RELATED


@pytest.mark.django_db
def test_creating_a_person_already_a_member_needs_no_approver():
    """The paper backlog is un-encodable if this fails. Spec section 3.2.2."""
    person = Person(
        last_name="Santos",
        first_name="Rhea",
        membership_status=MembershipStatus.MEMBER,
    )
    person.full_clean()
    person.save()
    assert person.approved_by is None


@pytest.mark.django_db
def test_changing_someone_to_member_requires_an_approver():
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    person.membership_status = MembershipStatus.MEMBER
    with pytest.raises(ValidationError) as exc:
        person.full_clean()
    assert "approved_by" in exc.value.message_dict


@pytest.mark.django_db
def test_changing_to_member_succeeds_with_an_approver():
    approver = Person.objects.create(last_name="Bilango", first_name="Alpha")
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    person.membership_status = MembershipStatus.MEMBER
    person.approved_by = approver
    person.full_clean()
    person.save()
    assert person.membership_status == MembershipStatus.MEMBER


@pytest.mark.django_db
def test_status_change_stamps_the_time():
    person = Person.objects.create(last_name="Daclitan", first_name="Kathleen")
    assert person.status_changed_at is not None
    first_stamp = person.status_changed_at

    person.membership_status = MembershipStatus.TRANSFERRED
    person.save()
    assert person.status_changed_at > first_stamp


@pytest.mark.django_db
def test_missing_data_flag_tracks_blank_fields():
    person = Person.objects.create(last_name="Abiagar", first_name="Sonia")
    assert person.has_missing_data is True

    person.date_of_birth = "1980-04-01"
    person.mobile_number = "09171234567"
    person.email = "sonia@example.com"
    person.home_address = "Km 5, La Trinidad, Benguet"
    person.civil_status = "MARRIED"
    person.save()
    assert person.has_missing_data is False


@pytest.mark.django_db
def test_full_name_collapses_blanks():
    person = Person(last_name="Malong", first_name="Shan", middle_name="Albert")
    assert person.full_name == "Shan Albert Malong"

    plain = Person(last_name="Yagui", first_name="Diana")
    assert plain.full_name == "Diana Yagui"
