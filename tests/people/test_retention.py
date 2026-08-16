import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from people.models import MembershipStatus, Person


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
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567", email="rhea@example.com",
        home_address="Km 5, La Trinidad", emergency_contact_name="Juan",
        date_of_birth=dt.date(1980, 2, 2),
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


@pytest.mark.django_db
def test_identity_and_membership_history_survive(transferred_long_ago):
    """Spec section 5.1: the register is permanent; only contact data expires."""
    call_command("purge_stale_contacts")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.last_name == "Santos"
    assert transferred_long_ago.date_of_birth == dt.date(1980, 2, 2)
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
