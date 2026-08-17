import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

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

    # Push the stamp a day back so the re-stamp is unambiguous. Two save()
    # calls within one clock tick would otherwise produce equal timestamps.
    past = timezone.now() - dt.timedelta(days=1)
    Person.objects.filter(pk=person.pk).update(status_changed_at=past)
    person.refresh_from_db()

    person.membership_status = MembershipStatus.TRANSFERRED
    person.save()

    assert person.status_changed_at > past


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
def test_refresh_from_db_resyncs_the_status_shadow():
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    past = timezone.now() - dt.timedelta(days=1)
    Person.objects.filter(pk=person.pk).update(
        membership_status=MembershipStatus.INACTIVE, status_changed_at=past
    )
    person.refresh_from_db()

    person.save()

    person.refresh_from_db()
    assert person.status_changed_at == past


@pytest.mark.django_db
def test_full_name_collapses_blanks():
    person = Person(last_name="Malong", first_name="Shan", middle_name="Albert")
    assert person.full_name == "Shan Albert Malong"

    plain = Person(last_name="Yagui", first_name="Diana")
    assert plain.full_name == "Diana Yagui"


@pytest.mark.django_db
def test_a_future_date_of_birth_is_refused():
    """IMPORTANT 4: docs/IMPORT_TEMPLATE.md promises AEGIS checks calendar
    validity itself -- a birth year of 2099 must not slip through
    full_clean() the way it used to."""
    person = Person(
        last_name="Bugnosen",
        first_name="Ivy",
        date_of_birth=timezone.localdate() + dt.timedelta(days=1),
    )
    with pytest.raises(ValidationError) as exc:
        person.full_clean()
    assert "date_of_birth" in exc.value.message_dict


@pytest.mark.django_db
def test_a_birth_date_of_today_is_allowed():
    """Not "future" -- a newborn's paper form filed the same day is real."""
    person = Person(last_name="Bugnosen", first_name="Baby", date_of_birth=timezone.localdate())
    person.full_clean()
    person.save()
    assert person.pk is not None


@pytest.mark.django_db
def test_a_decades_old_birth_year_from_the_paper_backlog_is_still_encodable():
    """The improbable, not the impossible, must stay encodable (IMPORTANT 4's
    explicit constraint) -- a member whose birth year was mis-keyed decades
    ago is not a future date and must not be refused."""
    person = Person(last_name="Old", first_name="Timer", date_of_birth=dt.date(1900, 1, 1))
    person.full_clean()
    person.save()
    assert person.pk is not None
