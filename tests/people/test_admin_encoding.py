import datetime as dt

import pytest
from django.contrib.auth.models import Group, User

from core import groups
from people.admin import describe_duplicate_match, find_possible_duplicates
from people.models import MembershipStatus, Person


@pytest.mark.django_db
def test_duplicates_are_found_by_name_and_birthdate():
    Person.objects.create(
        last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 3, 2)
    )
    candidate = Person(
        last_name="malong", first_name="SHAN", date_of_birth=dt.date(1995, 3, 2)
    )
    assert find_possible_duplicates(candidate).count() == 1


@pytest.mark.django_db
def test_a_shared_name_with_a_different_birthdate_is_not_a_duplicate():
    Person.objects.create(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1970, 1, 1)
    )
    candidate = Person(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1994, 9, 9)
    )
    assert find_possible_duplicates(candidate).count() == 0


@pytest.mark.django_db
def test_a_person_does_not_match_themselves():
    person = Person.objects.create(
        last_name="Reyes", first_name="Manex", date_of_birth=dt.date(1988, 7, 7)
    )
    assert find_possible_duplicates(person).count() == 0


@pytest.mark.django_db
def test_a_seeded_officer_with_no_birthdate_is_still_found_as_a_duplicate():
    """The reported bug, reproduced directly: seed_officers creates officers
    from data/officers.csv, which has no date-of-birth column, so every
    seeded chairperson sits in the register with date_of_birth = NULL. When
    that same person's own profiling form is imported later *with* a real
    birthdate, the old exact-match filter excluded the NULL row entirely and
    a second Person got created silently -- the volunteer's own bug report.
    An absent birthdate is not evidence of a different person.
    """
    Person.objects.create(last_name="Malong", first_name="Shan Albert")  # seeded, no DOB
    incoming = Person(
        last_name="Malong",
        first_name="Shan Albert",
        middle_name="Ganuelas",
        date_of_birth=dt.date(1995, 3, 2),
    )
    assert find_possible_duplicates(incoming).count() == 1


@pytest.mark.django_db
def test_a_candidate_with_no_birthdate_still_matches_on_name_alone():
    """Unchanged fallback: when the *incoming* record has no birthdate to
    compare, matching stays name-only, exactly as before this fix."""
    Person.objects.create(
        last_name="Reyes", first_name="Manex", date_of_birth=dt.date(1988, 7, 7)
    )
    candidate = Person(last_name="Reyes", first_name="Manex")
    assert find_possible_duplicates(candidate).count() == 1


@pytest.mark.django_db
def test_describe_duplicate_match_distinguishes_exact_from_weak_matches():
    """The reviewer deserves to know which kind of match they are looking
    at: an exact name-and-birthdate match is much stronger evidence than a
    name-only match against a record with no birthdate on file."""
    exact = Person.objects.create(
        last_name="Malong", first_name="Shan Albert", date_of_birth=dt.date(1995, 3, 2)
    )
    no_dob_on_file = Person.objects.create(last_name="Malong", first_name="Shan Albert")

    exact_description = describe_duplicate_match(exact, dt.date(1995, 3, 2))
    weak_description = describe_duplicate_match(no_dob_on_file, dt.date(1995, 3, 2))

    assert "same name and birthdate" in exact_description
    assert "no birthdate on file" in weak_description


@pytest.mark.django_db
def test_saving_a_person_over_a_seeded_officer_warns_and_names_the_weak_match(client):
    """End-to-end through the admin: approving/saving a new Person that
    duplicates a birthdate-less seeded officer must warn, and the warning
    text must say the existing record has no birthdate on file rather than
    implying an exact match that isn't there."""
    Person.objects.create(last_name="Malong", first_name="Shan Albert")  # seeded, no DOB
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    client.force_login(user)

    post = {
        "last_name": "Malong",
        "first_name": "Shan Albert",
        "middle_name": "Ganuelas",
        "suffix": "",
        "nickname": "",
        "date_of_birth": "1995-03-02",
        "place_of_birth": "",
        "gender": "",
        "civil_status": "",
        "nationality": "Filipino",
        "home_address": "",
        "mobile_number": "",
        "email": "",
        "emergency_contact_name": "",
        "emergency_contact_relationship": "",
        "emergency_contact_number": "",
        "guardian": "",
        "guardian_relationship": "",
        "membership_status": MembershipStatus.RELATED,
        "date_filed": "",
        "date_became_member": "",
        "approved_by": "",
        "date_of_death": "",
        "consent_date": "",
        "consent_version": "",
        "follow_up_notes": "",
        "notes": "",
        "household_memberships-TOTAL_FORMS": "0",
        "household_memberships-INITIAL_FORMS": "0",
        "household_memberships-MIN_NUM_FORMS": "0",
        "household_memberships-MAX_NUM_FORMS": "1000",
        "committee_memberships-TOTAL_FORMS": "0",
        "committee_memberships-INITIAL_FORMS": "0",
        "committee_memberships-MIN_NUM_FORMS": "0",
        "committee_memberships-MAX_NUM_FORMS": "1000",
        "scans-TOTAL_FORMS": "0",
        "scans-INITIAL_FORMS": "0",
        "scans-MIN_NUM_FORMS": "0",
        "scans-MAX_NUM_FORMS": "1000",
    }
    response = client.post("/admin/people/person/add/", post, follow=True)
    assert response.status_code == 200
    body = response.content.decode()
    assert "may duplicate an existing record" in body
    assert "no birthdate on file" in body
    # Never a block -- the second Person is created anyway.
    assert Person.objects.filter(date_of_birth=dt.date(1995, 3, 2)).exists()


@pytest.mark.django_db
def test_member_numbers_are_assigned_in_sequence_and_never_overwritten():
    """Day-one workflow: the Secretariat has already typed MEM-0099 in by
    hand off a paper form before anyone runs "Assign member numbers". The
    allocator must continue past it, not collide with it — MEM-0001 would
    be a second person holding the same number as "existing", which is the
    bug this test used to encode as expected behaviour.
    """
    from people.admin import assign_member_numbers

    existing = Person.objects.create(
        last_name="Daclitan",
        first_name="Kathleen",
        membership_status=MembershipStatus.MEMBER,
        member_no="MEM-0099",
    )
    fresh = Person.objects.create(
        last_name="Bilango", first_name="Alpha",
        membership_status=MembershipStatus.MEMBER,
    )

    assign_member_numbers(Person.objects.all())

    existing.refresh_from_db()
    fresh.refresh_from_db()
    assert existing.member_no == "MEM-0099"
    assert fresh.member_no == "MEM-0100"


@pytest.mark.django_db
def test_assign_member_numbers_reconciles_hand_entered_numbers_on_its_own():
    """The Secretariat must not have to remember to run the separate
    "reconcile_member_sequence" management command before assigning: the
    admin action itself must be safe against hand-entered numbers written
    in any order, including ones higher than anything the sequence has
    allocated so far.
    """
    from people.admin import assign_member_numbers

    Person.objects.create(
        last_name="Ureta", first_name="Jomar",
        membership_status=MembershipStatus.MEMBER,
        member_no="MEM-0150",
    )
    first_fresh = Person.objects.create(
        last_name="Bilango", first_name="Alpha",
        membership_status=MembershipStatus.MEMBER,
    )
    second_fresh = Person.objects.create(
        last_name="Cruz", first_name="Beta",
        membership_status=MembershipStatus.MEMBER,
    )

    assign_member_numbers(Person.objects.all())

    first_fresh.refresh_from_db()
    second_fresh.refresh_from_db()
    assigned = {first_fresh.member_no, second_fresh.member_no}
    assert assigned == {"MEM-0151", "MEM-0152"}


@pytest.mark.django_db
def test_a_denied_view_is_not_logged(client):
    from django.contrib.auth.models import User
    from records.models import AccessLog

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    nosy = User.objects.create_user("nosy", password="x", is_staff=True)
    client.force_login(nosy)

    client.get(f"/admin/people/person/{person.pk}/change/")

    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_a_permitted_view_is_logged(client):
    from django.contrib.auth.models import Group, User
    from records.models import AccessLog
    from core import groups

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    secretary = User.objects.create_user("sec", password="x", is_staff=True)
    secretary.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    client.force_login(secretary)

    client.get(f"/admin/people/person/{person.pk}/change/")

    entry = AccessLog.objects.get()
    assert entry.user == secretary
    assert entry.person == person


@pytest.mark.django_db
def test_the_access_log_cannot_be_deleted_through_the_admin():
    from django.contrib.admin.sites import AdminSite
    from records.admin import AccessLogAdmin
    from records.models import AccessLog

    admin_obj = AccessLogAdmin(AccessLog, AdminSite())
    assert admin_obj.has_delete_permission(None) is False


@pytest.mark.django_db
def test_a_refused_post_from_a_view_only_user_is_not_logged(client):
    from django.contrib.auth.models import Permission, User
    from records.models import AccessLog

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    viewer = User.objects.create_user("viewer", password="x", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_person"))
    client.force_login(viewer)

    client.post(f"/admin/people/person/{person.pk}/change/", {})

    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_a_view_only_user_reading_the_page_is_still_logged(client):
    from django.contrib.auth.models import Permission, User
    from records.models import AccessLog

    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    viewer = User.objects.create_user("viewer", password="x", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_person"))
    client.force_login(viewer)

    client.get(f"/admin/people/person/{person.pk}/change/")

    assert AccessLog.objects.get().person == person
