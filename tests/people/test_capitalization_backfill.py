"""backfill_capitalization closes two gaps at once (see people/models.py and
core/capitalization.py):

1. Household.address was never in Household.CAPITALIZED_FIELDS, so every
   address written before that changed stayed shouting.
2. Capitalization only ever runs inside save() -- a row written before the
   rule existed, or by any path that bypasses save() (a raw update(), a
   fixture, a direct SQL load), is never touched again on its own.

This command re-normalizes every existing Person and Household row in one
pass. It deliberately writes through queryset update(), not
Person.save()/Household.save() -- see the command's own `help` text for the
full reasoning -- so several tests below double as proof that decision
holds: no new Person.history revision is written by the backfill, even
though fields visibly change.

Test data is fabricated (fictional names), never drawn from `form images/`.
"""

import io

import pytest
from django.core.management import call_command

from people.models import Household, Person


def _force(model, pk, **fields):
    """Write field values the way a row from before the capitalization rule
    existed (or applied to this field) would already be sitting on disk --
    bypassing save() (and, for Person, django-simple-history) entirely via a
    raw queryset update(), the same technique tests/people/test_retention.py
    uses to simulate a pre-existing row."""
    model.objects.filter(pk=pk).update(**fields)


@pytest.mark.django_db
def test_backfill_converts_existing_uppercase_person_rows():
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(
        Person, person.pk,
        last_name="JOSE", first_name="MARK JEROME", middle_name="GANUELAS",
        home_address="KC-109 CRUZ, LA TRINIDAD, BENGUET", suffix="III",
    )

    call_command("backfill_capitalization")

    person.refresh_from_db()
    assert person.last_name == "Jose"
    assert person.first_name == "Mark Jerome"
    assert person.middle_name == "Ganuelas"
    assert person.home_address == "KC-109 Cruz, La Trinidad, Benguet"
    assert person.suffix == "III"  # Roman numeral -- must not become "Iii"


@pytest.mark.django_db
def test_backfill_converts_existing_uppercase_household_rows():
    household = Household.objects.create(name="Cruz Family")
    _force(
        Household, household.pk,
        name="CRUZ FAMILY", address="KC-109 CRUZ, LA TRINIDAD, BENGUET",
    )

    call_command("backfill_capitalization")

    household.refresh_from_db()
    assert household.name == "Cruz Family"
    assert household.address == "KC-109 Cruz, La Trinidad, Benguet"


@pytest.mark.django_db
def test_backfill_normalizes_a_shouting_jr_suffix():
    person = Person.objects.create(last_name="Cruz", first_name="Juan")
    _force(Person, person.pk, suffix="JR")

    call_command("backfill_capitalization")

    person.refresh_from_db()
    assert person.suffix == "Jr"


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    """Proven, not asserted: read every field back from the database after
    a --dry-run and show it is exactly what it was before the command ran."""
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, person.pk, last_name="JOSE", first_name="MARK")
    household = Household.objects.create(name="Cruz Family")
    _force(Household, household.pk, name="CRUZ FAMILY", address="SESSION ROAD")

    call_command("backfill_capitalization", "--dry-run")

    person.refresh_from_db()
    household.refresh_from_db()
    assert person.last_name == "JOSE"
    assert person.first_name == "MARK"
    assert household.name == "CRUZ FAMILY"
    assert household.address == "SESSION ROAD"


@pytest.mark.django_db
def test_dry_run_reports_what_would_change():
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, person.pk, last_name="JOSE")

    out = io.StringIO()
    call_command("backfill_capitalization", "--dry-run", stdout=out)
    assert "Would capitalize 1 person(s) and 0 household(s)." in out.getvalue()


@pytest.mark.django_db
def test_running_twice_changes_nothing_the_second_time():
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, person.pk, last_name="JOSE", first_name="MARK JEROME")
    household = Household.objects.create(name="Cruz Family", address="Session Road")
    _force(Household, household.pk, address="SESSION ROAD")

    call_command("backfill_capitalization")
    person.refresh_from_db()
    household.refresh_from_db()
    first_pass_last_name = person.last_name
    first_pass_address = household.address

    out = io.StringIO()
    call_command("backfill_capitalization", stdout=out)

    person.refresh_from_db()
    household.refresh_from_db()
    assert person.last_name == first_pass_last_name
    assert household.address == first_pass_address
    assert "Capitalized 0 person(s) and 0 household(s)." in out.getvalue()


@pytest.mark.django_db
def test_a_person_with_correct_casing_is_untouched():
    """McDonald / dela Cruz must survive the backfill exactly as typed --
    the normalizer only reshapes a field that is entirely uppercase."""
    person = Person.objects.create(
        last_name="McDonald", first_name="dela Cruz", home_address="Km 5, La Trinidad"
    )

    call_command("backfill_capitalization")

    person.refresh_from_db()
    assert person.last_name == "McDonald"
    assert person.first_name == "dela Cruz"
    assert person.home_address == "Km 5, La Trinidad"


@pytest.mark.django_db
def test_backfill_writes_no_new_history_revision():
    """The deliberate decision this command makes: it writes through
    queryset update(), never Person.save(), so a purely cosmetic re-casing
    does not fabricate a historical revision stamped at backfill time with
    no real author. Confirmed here directly against Person.history."""
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, person.pk, last_name="JOSE", first_name="MARK JEROME")
    history_count_before = Person.history.filter(id=person.pk).count()
    assert history_count_before == 1  # only the original create()

    call_command("backfill_capitalization")

    person.refresh_from_db()
    assert person.last_name == "Jose"  # the field did change...
    assert (
        Person.history.filter(id=person.pk).count() == history_count_before
    )  # ...but no new revision was written for it


@pytest.mark.django_db
def test_backfill_does_not_disturb_has_missing_data_or_status_changed_at():
    """update() skips Person.save()'s other bookkeeping entirely. That is
    safe here only because neither value can actually change from a
    capitalization backfill -- pinned down directly."""
    person = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, person.pk, last_name="JOSE")
    has_missing_data_before = person.has_missing_data
    status_changed_at_before = person.status_changed_at

    call_command("backfill_capitalization")

    person.refresh_from_db()
    assert person.has_missing_data == has_missing_data_before
    assert person.status_changed_at == status_changed_at_before


@pytest.mark.django_db
def test_blank_fields_are_handled_without_error():
    person = Person.objects.create(last_name="Cruz", first_name="Juan")
    household = Household.objects.create(name="Cruz Family")
    call_command("backfill_capitalization")  # must not raise
    person.refresh_from_db()
    household.refresh_from_db()
    assert person.middle_name == ""
    assert household.address == ""


@pytest.mark.django_db
def test_a_single_shouting_character_is_handled_without_error():
    person = Person.objects.create(last_name="Cruz", first_name="Juan")
    _force(Person, person.pk, nickname="J")

    call_command("backfill_capitalization")  # must not raise

    person.refresh_from_db()
    assert person.nickname == "J"


@pytest.mark.django_db
def test_backfill_reports_a_count_and_is_quiet_about_unchanged_rows():
    changed = Person.objects.create(last_name="Jose", first_name="Mark")
    _force(Person, changed.pk, last_name="JOSE")
    Person.objects.create(last_name="McDonald", first_name="Dela Cruz")  # already correct

    out = io.StringIO()
    call_command("backfill_capitalization", stdout=out)

    assert "Capitalized 1 person(s) and 0 household(s)." in out.getvalue()
