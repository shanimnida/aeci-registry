import datetime as dt

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.utils import timezone

from committees.admin import CommitteeMembershipAdmin
from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
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
    mine = CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
    )
    on_my_committee_membership = CommitteeMembership.objects.create(
        committee=ict, person=on_my_committee, role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    stranger_membership = CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, on_my_committee_membership, stranger_membership


def request_for(user):
    request = RequestFactory().get("/admin/committees/committeemembership/")
    request.user = user
    return request


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committees_memberships(chair_setup):
    user, mine, stranger = chair_setup
    admin = CommitteeMembershipAdmin(CommitteeMembership, AdminSite())
    visible = admin.get_queryset(request_for(user))
    assert mine in visible
    assert stranger not in visible


@pytest.mark.django_db
def test_a_chairperson_cannot_read_committee_membership_history(client, chair_setup):
    user, mine, _ = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/committees/committeemembership/{mine.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_read_a_strangers_committee_membership_history(client, chair_setup):
    user, _, stranger = chair_setup
    client.force_login(user)
    response = client.get(f"/admin/committees/committeemembership/{stranger.pk}/history/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_the_board_sees_every_membership(db):
    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    food = Committee.objects.get(code="food")
    CommitteeMembership.objects.create(
        committee=food, person=person, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )
    user = User.objects.create_user("board", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.BOARD))
    admin = CommitteeMembershipAdmin(CommitteeMembership, AdminSite())
    assert admin.get_queryset(request_for(user)).count() == 1


@pytest.mark.django_db
def test_a_chairperson_cannot_filter_the_changelist_by_a_withheld_person_field(
    client, chair_setup
):
    """Same defect as people.admin.PersonAdmin's Spec D12 fix, smaller blast
    radius: get_queryset row-scopes which memberships a chairperson sees, but
    that happens *after* Django's changelist applies any
    ?field__lookup=value querystring filter. Nothing stopped
    ?person__home_address__icontains=...  from reading a chaired committee
    member's withheld Person fields back out through which rows appear or
    vanish — a binary search over repeated requests would recover an address
    or a birthdate one bit at a time, same as the PersonAdmin exploit shape.
    """
    user, _, _ = chair_setup
    client.force_login(user)
    response = client.get(
        "/admin/committees/committeemembership/",
        {"person__home_address__icontains": "Pines"},
    )
    assert response.status_code == 400

    response = client.get(
        "/admin/committees/committeemembership/",
        {"person__date_of_birth__year": "1985"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_chairperson_can_still_filter_by_permitted_fields(client, chair_setup):
    """The fix for the above must not be a blanket lockout: filtering by one
    of the five permitted Person fields, or by one of the membership's own
    fields, has to keep working and keep returning the right rows.
    """
    user, mine, stranger = chair_setup
    client.force_login(user)

    response = client.get(
        "/admin/committees/committeemembership/",
        {"person__last_name": mine.person.last_name},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert mine.person.last_name in body
    assert stranger.person.last_name not in body

    response = client.get(
        "/admin/committees/committeemembership/",
        {"committee": mine.committee_id},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert mine.person.last_name in body
    assert stranger.person.last_name not in body


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.SECRETARIAT, groups.ICT])
def test_secretariat_and_ict_can_still_filter_by_anything_they_could_before(
    client, chair_setup, group_name
):
    """These roles are not row-scoped and never went through the
    chairperson-only branch of lookup_allowed, so the fix must not touch
    what they could already do: filter the full roster by the membership's
    own fields.
    """
    _, mine, stranger = chair_setup
    user = User.objects.create_user(f"wide-{group_name}", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    client.force_login(user)

    response = client.get(
        "/admin/committees/committeemembership/",
        {"committee": mine.committee_id},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert mine.person.last_name in body
    assert stranger.person.last_name not in body


@pytest.mark.django_db
def test_a_chairperson_gets_403_on_the_appointment_changelist(client, chair_setup):
    """AppointmentAdmin is also a SimpleHistoryAdmin in committees/admin.py.
    The Chairperson group holds view_person, view_committee and
    view_committeemembership only (core/migrations/0002_create_groups.py) —
    no view_appointment — so this changelist should already be unreachable
    without any lookup_allowed override of its own. Verified through the
    test client rather than assumed from the permission table.
    """
    user, _, _ = chair_setup
    client.force_login(user)
    response = client.get("/admin/committees/appointment/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_third_self_selected_committee_saves_and_warns_in_the_admin(client):
    """Same shape as people.admin.PersonAdmin.save_model's duplicate-person
    warning: a Secretariat user adding a third self-selected MEMBER
    committee for someone through the admin must have it save (not be
    refused), with a WARNING message naming the count and the profiling
    form's own printed cap of two. See
    CommitteeMembership.self_selected_overflow_count.
    """
    person = Person.objects.create(last_name="Cruz", first_name="Ana")
    ict = Committee.objects.get(code="ict")
    events = Committee.objects.get(code="events")
    food = Committee.objects.get(code="food")
    CommitteeMembership.objects.create(
        committee=ict, person=person, role=CommitteeRole.MEMBER, date_joined=JOINED
    )
    CommitteeMembership.objects.create(
        committee=events, person=person, role=CommitteeRole.MEMBER, date_joined=JOINED
    )

    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    client.force_login(user)

    response = client.post(
        "/admin/committees/committeemembership/add/",
        {
            "committee": food.pk,
            "person": person.pk,
            "function": "",
            "role": CommitteeRole.MEMBER,
            "date_joined": JOINED.isoformat(),
            "date_left": "",
            "_save": "Save",
        },
        follow=True,
    )
    assert response.status_code == 200
    assert (
        CommitteeMembership.objects.filter(person=person, role=CommitteeRole.MEMBER).count() == 3
    )

    warnings = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("3 self-selected" in m for m in warnings)
    assert any("up to 2" in m for m in warnings)
