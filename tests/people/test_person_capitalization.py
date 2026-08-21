"""The volunteer's ask: paper forms are filled in block capitals, and the
Secretariat wants "Mark Jerome Ganuelas Jose", not the register shouting
"MARK JEROME GANUELAS JOSE" back at them. Normalized at the model level
(Person.save() / Household.save(), both calling core.capitalization) so it
applies the same way whether the row was typed in the admin or created by
the import approval workflow -- see imports/services.py's
build_person_from_import(), which builds a Person the same way.

The pure-function edge cases (acronyms, apostrophes, particles, blank
input...) are pinned down directly against core.capitalization in
tests/core/test_capitalization.py. This file checks the model actually
calls it, on every listed field, and does not call it on the fields that
must never be touched.
"""

import pytest

from people.models import Household, Person


@pytest.mark.django_db
def test_all_caps_person_fields_are_title_cased_on_save():
    """The volunteer's own example, end to end."""
    person = Person.objects.create(
        last_name="JOSE",
        first_name="MARK JEROME",
        middle_name="GANUELAS",
        home_address="KC-109 CRUZ, LA TRINIDAD, BENGUET",
    )
    assert person.last_name == "Jose"
    assert person.first_name == "Mark Jerome"
    assert person.middle_name == "Ganuelas"
    assert person.home_address == "KC-109 Cruz, La Trinidad, Benguet"


@pytest.mark.django_db
def test_the_normalized_value_is_what_is_actually_persisted():
    person = Person.objects.create(last_name="DELA CRUZ", first_name="JUAN")
    person.refresh_from_db()
    assert person.last_name == "Dela Cruz"


@pytest.mark.django_db
def test_every_listed_field_is_normalized():
    person = Person.objects.create(
        last_name="SANTOS",
        first_name="ANA",
        middle_name="REYES",
        nickname="ANA",
        place_of_birth="BAGUIO CITY",
        home_address="SESSION ROAD, BAGUIO CITY",
        nationality="FILIPINO",
        emergency_contact_name="PEDRO SANTOS",
        emergency_contact_relationship="FATHER",
        guardian_relationship="GRANDMOTHER",
    )
    assert person.nickname == "Ana"
    assert person.place_of_birth == "Baguio City"
    assert person.home_address == "Session Road, Baguio City"
    assert person.nationality == "Filipino"
    assert person.emergency_contact_name == "Pedro Santos"
    assert person.emergency_contact_relationship == "Father"
    assert person.guardian_relationship == "Grandmother"


@pytest.mark.django_db
def test_email_is_never_touched():
    person = Person.objects.create(
        last_name="JOSE", first_name="MARK", email="mjjose1925@gmail.com"
    )
    assert person.email == "mjjose1925@gmail.com"


@pytest.mark.django_db
def test_an_all_caps_email_is_still_never_touched():
    """Not lowered either -- capitalization never runs on this field at
    all, in either direction."""
    person = Person(last_name="JOSE", first_name="MARK")
    person.email = "MJJOSE1925@GMAIL.COM"
    person.save()
    assert person.email == "MJJOSE1925@GMAIL.COM"


@pytest.mark.django_db
def test_phone_numbers_are_never_touched():
    person = Person.objects.create(
        last_name="JOSE",
        first_name="MARK",
        mobile_number="0991-922-6025",
        emergency_contact_number="0991 922 6034",
    )
    assert person.mobile_number == "0991-922-6025"
    assert person.emergency_contact_number == "0991 922 6034"


@pytest.mark.django_db
def test_member_no_is_never_touched():
    person = Person.objects.create(last_name="JOSE", first_name="MARK", member_no="MEM-0001")
    assert person.member_no == "MEM-0001"


@pytest.mark.django_db
def test_suffix_roman_numeral_is_not_mangled():
    person = Person.objects.create(last_name="CRUZ", first_name="JUAN", suffix="III")
    assert person.suffix == "III"


@pytest.mark.django_db
def test_suffix_jr_is_title_cased():
    person = Person.objects.create(last_name="CRUZ", first_name="JUAN", suffix="JR.")
    assert person.suffix == "Jr."


@pytest.mark.django_db
def test_already_mixed_case_names_are_not_mangled():
    """Someone typing "McDonald" or "dela Cruz" by hand must get exactly
    that back, not a "corrected" version."""
    person = Person.objects.create(last_name="McDonald", first_name="dela Cruz")
    assert person.last_name == "McDonald"
    assert person.first_name == "dela Cruz"


@pytest.mark.django_db
def test_a_blank_field_survives_save_as_blank():
    person = Person.objects.create(last_name="CRUZ", first_name="JUAN")
    assert person.middle_name == ""
    assert person.home_address == ""


@pytest.mark.django_db
def test_a_single_character_field_is_handled():
    person = Person.objects.create(last_name="CRUZ", first_name="JUAN", nickname="J")
    assert person.nickname == "J"


@pytest.mark.django_db
def test_a_trailing_space_is_preserved_through_a_real_save():
    person = Person.objects.create(last_name="CRUZ", first_name="MARK ")
    assert person.first_name == "Mark "


@pytest.mark.django_db
def test_household_name_is_title_cased_when_shouting():
    household = Household.objects.create(name="JOSE FAMILY")
    assert household.name == "Jose Family"


@pytest.mark.django_db
def test_household_name_already_mixed_case_is_left_alone():
    household = Household.objects.create(name="Jose Family")
    assert household.name == "Jose Family"


@pytest.mark.django_db
def test_household_address_is_title_cased_when_shouting():
    """Household.address holds the same kind of street address as
    Person.home_address and must be normalized the same way."""
    household = Household.objects.create(
        name="Cruz Family", address="KC-109 CRUZ, LA TRINIDAD, BENGUET"
    )
    assert household.address == "KC-109 Cruz, La Trinidad, Benguet"


@pytest.mark.django_db
def test_household_address_already_mixed_case_is_left_alone():
    household = Household.objects.create(
        name="Cruz Family", address="123 Session Road, Baguio City"
    )
    assert household.address == "123 Session Road, Baguio City"


@pytest.mark.django_db
def test_household_blank_address_survives_save_as_blank():
    household = Household.objects.create(name="Cruz Family")
    assert household.address == ""
