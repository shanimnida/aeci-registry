import datetime as dt

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.test import RequestFactory
from django.utils import timezone

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.admin import CHAIRPERSON_FIELDS, PersonAdmin
from people.models import Person

TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=7)


@pytest.fixture
def chair_setup(db):
    chair_person = Person.objects.create(last_name="Malong", first_name="Shan")
    on_my_committee = Person.objects.create(last_name="Reyes", first_name="Manex")
    stranger = Person.objects.create(last_name="Santos", first_name="Rhea")

    ict = Committee.objects.get(code="ict")
    food = Committee.objects.get(code="food")
    CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=ict, person=on_my_committee, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, on_my_committee, stranger


def request_for(user):
    request = RequestFactory().get("/admin/people/person/")
    request.user = user
    return request


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committee(chair_setup):
    user, mine, stranger = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    visible = admin.get_queryset(request_for(user))
    assert mine in visible
    assert stranger not in visible


#: Field name -> the label Django auto-derives for it (name.replace("_", " "),
#: capfirst'd) and what Unfold's readonly field template actually renders —
#: see test_a_chairperson_sees_only_five_fields for why the raw field name
#: itself never appears in the markup a chairperson receives.
FIELD_LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "nickname": "Nickname",
    "mobile_number": "Mobile number",
    "email": "Email",
    "home_address": "Home address",
    "date_of_birth": "Date of birth",
    "civil_status": "Civil status",
    "notes": "Notes",
    "user": "User",
}


@pytest.mark.django_db
def test_a_chairperson_sees_only_five_fields(client, chair_setup):
    # get_fields() is not the right probe here: Django only calls it when
    # `fieldsets` is undefined. PersonAdmin defines `fieldsets`, so the
    # actual change form is built from get_fieldsets() instead — asserting
    # against get_fields() would pass even if get_fieldsets() leaked every
    # field. Fetch the rendered page a chairperson would actually receive.
    #
    # The Chairperson group holds view_person but never change_person (see
    # core/migrations/0002_create_groups.py), so this always renders as a
    # read-only page: Unfold's readonly field template prints a label like
    # ">First name<", never a `name="first_name"` form control. That's the
    # marker to look for, not an input's name attribute.
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/people/person/{mine.pk}/change/")
    body = response.content.decode()
    for field in CHAIRPERSON_FIELDS:
        assert f">{FIELD_LABELS[field]}<" in body


@pytest.mark.django_db
def test_a_chairperson_never_sees_an_address_or_birthdate(client, chair_setup):
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/people/person/{mine.pk}/change/")
    body = response.content.decode()
    for hidden in ("home_address", "date_of_birth", "civil_status", "notes"):
        assert f">{FIELD_LABELS[hidden]}<" not in body


@pytest.mark.django_db
def test_the_secretariat_sees_everyone(db):
    Person.objects.create(last_name="Santos", first_name="Rhea")
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    admin = PersonAdmin(Person, AdminSite())
    assert admin.get_queryset(request_for(user)).count() == 1


@pytest.mark.django_db
def test_a_chairperson_cannot_read_history_for_their_own_roster(client, chair_setup):
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/people/person/{mine.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_read_history_for_a_stranger(client, chair_setup):
    user, _, stranger = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/people/person/{stranger.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_the_chairperson_changelist_hides_withheld_columns(client, chair_setup):
    user, _, _ = chair_setup
    client.force_login(user)
    response = client.get("/admin/people/person/")
    body = response.content.decode()
    assert "column-member_no" not in body
    assert "column-membership_status" not in body


@pytest.mark.django_db
def test_a_chairperson_cannot_filter_the_changelist_by_a_withheld_field(client, chair_setup):
    """Defect 1: rendering hides the field, but nothing stopped a
    ?date_of_birth__year=1985-style querystring filter from reading it back
    out through which rows appear. That has to be refused at the URL layer,
    not merely left off the page — a binary search over repeated requests
    would otherwise recover a birthdate or an address one bit at a time.
    """
    user, _, _ = chair_setup
    client.force_login(user)
    response = client.get(
        "/admin/people/person/", {"date_of_birth__year": "1985"}
    )
    assert response.status_code == 400

    response = client.get(
        "/admin/people/person/", {"home_address__icontains": "Pines"}
    )
    assert response.status_code == 400

    response = client.get(
        "/admin/people/person/", {"civil_status__exact": "MARRIED"}
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_chairperson_can_still_filter_the_changelist_by_a_permitted_field(
    client, chair_setup
):
    """The fix for Defect 1 must not be a blanket lockout: filtering on one
    of the five permitted fields has to keep working.
    """
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(
        "/admin/people/person/", {"first_name__icontains": mine.first_name}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert mine.last_name in body


@pytest.mark.django_db
def test_someone_who_left_the_committee_is_no_longer_visible(chair_setup):
    user, mine, _ = chair_setup
    membership = CommitteeMembership.objects.get(person=mine)
    membership.date_left = TODAY - dt.timedelta(days=1)
    membership.save()

    admin_obj = PersonAdmin(Person, AdminSite())
    assert mine not in admin_obj.get_queryset(request_for(user))


@pytest.mark.django_db
def test_ict_sees_the_user_field(db):
    # get_fields() is not the right probe here: without an explicit `fields`
    # attribute, Django's ModelAdmin.get_fields() bypasses get_fieldsets()
    # entirely and returns almost every model field regardless of role. The
    # actual change form — what get_form() builds — is what respects
    # get_fieldsets(), so that is what to check.
    person = Person.objects.create(last_name="Malong", first_name="Shan")
    user = User.objects.create_user("ict", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.ICT))
    admin = PersonAdmin(Person, AdminSite())
    form = admin.get_form(request_for(user), person)
    assert "user" in form.base_fields


@pytest.mark.django_db
def test_the_secretariat_does_not_see_the_user_field(db):
    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    user = User.objects.create_user("sec2", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    admin = PersonAdmin(Person, AdminSite())
    form = admin.get_form(request_for(user), person)
    assert "user" not in form.base_fields


@pytest.mark.django_db
def test_a_chairperson_only_user_still_sees_exactly_five_fields(client, chair_setup):
    """The ICT branch in get_fieldsets must be additive: it must not leak
    the "user" field, or anything else, into the chairperson-only view.

    Checked against the rendered page, not get_fields() — see
    test_a_chairperson_sees_only_five_fields for why that probe is wrong
    once fieldsets is defined.
    """
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/people/person/{mine.pk}/change/")
    body = response.content.decode()
    for field in CHAIRPERSON_FIELDS:
        assert f">{FIELD_LABELS[field]}<" in body
    assert f">{FIELD_LABELS['user']}<" not in body


@pytest.mark.django_db
def test_linking_a_person_to_a_user_unlocks_the_committee_roster(db):
    """The end-to-end behaviour Defect 1 was blocking: before the fix,
    nothing could set Person.user through the admin, so a chairperson's
    roster was always empty. Here ICT links the login through the exact
    form field the fix exposes, and the roster comes into view.
    """
    chair_person = Person.objects.create(last_name="Malong", first_name="Shan")
    on_my_committee = Person.objects.create(last_name="Reyes", first_name="Manex")

    ict_committee = Committee.objects.get(code="ict")
    CommitteeMembership.objects.create(
        committee=ict_committee, person=chair_person,
        role=CommitteeRole.CHAIRPERSON, date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=ict_committee, person=on_my_committee,
        role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    chair_user = User.objects.create_user("chair3", password="x", is_staff=True)
    chair_user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))

    admin_obj = PersonAdmin(Person, AdminSite())
    assert on_my_committee not in admin_obj.get_queryset(request_for(chair_user))

    ict_user = User.objects.create_user("ict3", password="x", is_staff=True)
    ict_user.groups.add(Group.objects.get(name=groups.ICT))

    Form = admin_obj.get_form(request_for(ict_user), chair_person)
    form = Form(
        data={
            "last_name": chair_person.last_name,
            "first_name": chair_person.first_name,
            "membership_status": chair_person.membership_status,
            "user": chair_user.pk,
        },
        instance=chair_person,
    )
    assert form.is_valid(), form.errors
    form.save()

    chair_person.refresh_from_db()
    assert chair_person.user_id == chair_user.pk
    assert on_my_committee in admin_obj.get_queryset(request_for(chair_user))
