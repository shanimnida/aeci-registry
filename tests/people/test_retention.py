import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)
from records.models import PurgeRecord


def _stamp(person, days_ago):
    Person.objects.filter(pk=person.pk).update(
        status_changed_at=timezone.now() - dt.timedelta(days=days_ago)
    )
    person.refresh_from_db()
    return person


@pytest.fixture
def transferred_long_ago(db):
    person = Person.objects.create(
        last_name="Santos", first_name="Rhea",
        member_no="M-0042",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567", email="rhea@example.com",
        home_address="Km 5, La Trinidad", emergency_contact_name="Juan",
        emergency_contact_relationship="Spouse", emergency_contact_number="09179998888",
        date_of_birth=dt.date(1980, 2, 2), date_became_member=dt.date(2010, 5, 1),
    )
    return _stamp(person, 800)


@pytest.mark.django_db
def test_contact_details_are_cleared_after_two_years(transferred_long_ago):
    call_command("purge_stale_contacts")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.mobile_number == ""
    assert transferred_long_ago.email == ""
    assert transferred_long_ago.home_address == ""
    assert transferred_long_ago.emergency_contact_name == ""
    assert transferred_long_ago.emergency_contact_relationship == ""
    assert transferred_long_ago.emergency_contact_number == ""


@pytest.mark.django_db
def test_deceased_contact_details_are_cleared_after_two_years(db):
    person = Person.objects.create(
        last_name="Bagtas", first_name="Elena",
        membership_status=MembershipStatus.DECEASED,
        mobile_number="09171234567", email="elena@example.com",
        home_address="Km 4, La Trinidad", emergency_contact_name="Rosa",
        emergency_contact_relationship="Daughter", emergency_contact_number="09179876543",
    )
    _stamp(person, 800)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == ""
    assert person.email == ""
    assert person.home_address == ""
    assert person.emergency_contact_name == ""
    assert person.emergency_contact_relationship == ""
    assert person.emergency_contact_number == ""


@pytest.mark.django_db
def test_729_days_since_status_change_is_not_yet_stale(db):
    person = Person.objects.create(
        last_name="Cabrera", first_name="Boundary729",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567",
    )
    _stamp(person, 729)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == "09171234567"


@pytest.mark.django_db
def test_731_days_since_status_change_is_stale(db):
    person = Person.objects.create(
        last_name="Cabrera", first_name="Boundary731",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567",
    )
    _stamp(person, 731)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == ""


@pytest.mark.django_db
def test_identity_and_membership_history_survive(transferred_long_ago):
    """Spec section 5.1: the register is permanent; only contact data expires."""
    call_command("purge_stale_contacts")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.last_name == "Santos"
    assert transferred_long_ago.date_of_birth == dt.date(1980, 2, 2)
    assert transferred_long_ago.member_no == "M-0042"
    assert transferred_long_ago.date_became_member == dt.date(2010, 5, 1)
    assert transferred_long_ago.membership_status == MembershipStatus.TRANSFERRED
    assert Person.objects.filter(pk=transferred_long_ago.pk).exists()


@pytest.mark.django_db
def test_a_recent_transfer_is_left_alone(db):
    person = Person.objects.create(
        last_name="Reyes", first_name="Manex",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567",
    )
    _stamp(person, 100)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == "09171234567"


@pytest.mark.django_db
def test_active_members_are_never_purged(db):
    person = Person.objects.create(
        last_name="Malong", first_name="Shan",
        membership_status=MembershipStatus.MEMBER,
        mobile_number="09764215865",
    )
    _stamp(person, 5000)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == "09764215865"


@pytest.mark.django_db
def test_dry_run_changes_nothing(transferred_long_ago):
    call_command("purge_stale_contacts", "--dry-run")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.mobile_number == "09171234567"


@pytest.mark.django_db
def test_purge_scrubs_every_historical_revision():
    """Spec section 5.1: clearing only the live row leaves every prior value
    readable on the admin history page, so the retention policy would not be
    delivered."""
    person = Person.objects.create(
        last_name="Cruz", first_name="Nico",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171111111", email="nico1@example.com",
        home_address="Baguio City", emergency_contact_name="Ana",
        emergency_contact_relationship="Sister", emergency_contact_number="09172222222",
    )
    person.mobile_number = "09173333333"
    person.save()
    person.email = "nico2@example.com"
    person.save()
    _stamp(person, 800)

    assert Person.history.filter(id=person.pk).count() >= 3

    call_command("purge_stale_contacts")

    for record in Person.history.filter(id=person.pk):
        for field in Person.CONTACT_FIELDS:
            assert getattr(record, field) == "", (
                f"{field} survives on a historical revision"
            )


@pytest.mark.django_db
def test_purge_writes_a_purge_record(transferred_long_ago):
    call_command("purge_stale_contacts")
    record = PurgeRecord.objects.get(person=transferred_long_ago)
    assert record.person_label == "M-0042 Rhea Santos"
    assert record.history_rows_scrubbed >= 1


@pytest.mark.django_db
def test_dry_run_writes_no_purge_record(transferred_long_ago):
    call_command("purge_stale_contacts", "--dry-run")
    assert not PurgeRecord.objects.exists()


@pytest.mark.django_db
def test_household_address_cleared_once_vacated():
    """A household is shared; its address may only be cleared once nobody
    still current lives there. Here the only member has long since died."""
    household = Household.objects.create(name="Cruz Family", address="123 Session Road")
    person = Person.objects.create(
        last_name="Cruz", first_name="Departed",
        membership_status=MembershipStatus.DECEASED,
    )
    _stamp(person, 800)
    HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )

    call_command("purge_stale_contacts")
    household.refresh_from_db()
    assert household.address == ""


@pytest.mark.django_db
def test_household_address_kept_while_a_member_is_still_current():
    """One spouse transferred out; the other still attends, so the family's
    address is still legitimately needed and must not be cleared."""
    household = Household.objects.create(name="Reyes Family", address="45 Otek Street")
    transferred = Person.objects.create(
        last_name="Reyes", first_name="Left",
        membership_status=MembershipStatus.TRANSFERRED,
    )
    _stamp(transferred, 800)
    still_here = Person.objects.create(
        last_name="Reyes", first_name="Stayed",
        membership_status=MembershipStatus.MEMBER,
    )
    HouseholdMember.objects.create(
        household=household, person=transferred, role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=household, person=still_here, role=HouseholdRole.SPOUSE
    )

    call_command("purge_stale_contacts")
    household.refresh_from_db()
    assert household.address == "45 Otek Street"


@pytest.mark.django_db
def test_dry_run_does_not_touch_household_address():
    household = Household.objects.create(name="Cruz Family", address="123 Session Road")
    person = Person.objects.create(
        last_name="Cruz", first_name="Departed",
        membership_status=MembershipStatus.DECEASED,
    )
    _stamp(person, 800)
    HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )

    call_command("purge_stale_contacts", "--dry-run")
    household.refresh_from_db()
    assert household.address == "123 Session Road"
