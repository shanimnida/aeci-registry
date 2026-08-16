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
def test_a_report_view_is_logged_without_naming_a_person():
    """A report entry names the report, not each person listed in it.

    That one-entry-per-report guarantee is enforced at the call site in the
    admin (Task 10); here we only check the model supports the shape.
    """
    user = User.objects.create_user("sunshine", password="x")
    AccessLog.record(user=user, report="birthdays:next-30-days")
    entry = AccessLog.objects.get()
    assert entry.person is None
    assert entry.report == "birthdays:next-30-days"


@pytest.mark.django_db
def test_record_requires_exactly_one_of_person_or_report():
    user = User.objects.create_user("registrar", password="x")
    person = Person.objects.create(last_name="Reyes", first_name="Ana")

    with pytest.raises(ValueError):
        AccessLog.record(user=user)

    with pytest.raises(ValueError):
        AccessLog.record(user=user, person=person, report="birthdays:next-30-days")
