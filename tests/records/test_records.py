import pytest
from django.contrib.auth.models import User

from people.models import Person
from records.models import AccessLog, FormScan, FormType


@pytest.mark.django_db
def test_a_scan_can_exist_before_it_is_linked_to_anyone():
    """Photos get uploaded in a batch, then matched to people during encoding."""
    scan = FormScan.objects.create(form_type=FormType.MEMBER_PROFILING)
    assert scan.person is None


@pytest.mark.django_db
def test_a_scan_links_to_a_person():
    person = Person.objects.create(last_name="Malong", first_name="Shan")
    scan = FormScan.objects.create(person=person, form_type=FormType.MEMBER_PROFILING)
    assert person.scans.count() == 1
    assert scan.get_form_type_display() == "Member Profiling Form"


@pytest.mark.django_db
def test_viewing_a_person_is_recorded():
    user = User.objects.create_user("secretariat", password="x")
    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    AccessLog.record(user=user, person=person, ip="10.0.0.1")
    entry = AccessLog.objects.get()
    assert entry.user == user
    assert entry.person == person
    assert entry.ip_address == "10.0.0.1"


@pytest.mark.django_db
def test_a_report_writes_one_entry_not_one_per_row():
    """Spec section 7.6: per-row logging buries the signal the log exists for."""
    user = User.objects.create_user("sunshine", password="x")
    for name in ("A", "B", "C"):
        Person.objects.create(last_name=name, first_name="X")
    AccessLog.record(user=user, report="birthdays:next-30-days")
    assert AccessLog.objects.count() == 1
    assert AccessLog.objects.get().person is None
