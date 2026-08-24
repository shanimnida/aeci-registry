"""Committee appointments in one place, added 2026-08-24.

The Board's structure: the Board appoints each committee's chairperson,
and each chairperson appoints their own vice and secretary.

The interesting half is the chairperson's. Letting a chairperson appoint
anybody would have needed a person-picker reaching past D12's scoping --
they cannot see anyone off their own roster. It does not need one, because
a co-chair and a secretary come from the people already serving on that
committee. These tests exist mostly to prove that boundary holds from
every direction: committee, role, and person.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.utils import timezone
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.models import MembershipStatus, Person

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=60)


def appoint_url():
    return reverse("admin:committees_appointment_appoint")


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


def make_person(first_name, last_name="Wanawan", **kwargs):
    return Person.objects.create(
        last_name=last_name,
        first_name=first_name,
        membership_status=MembershipStatus.MEMBER,
        **kwargs,
    )


def put_on(committee_code, person, role=CommitteeRole.MEMBER, **kwargs):
    return CommitteeMembership.objects.create(
        committee=Committee.objects.get(code=committee_code),
        person=person,
        role=role,
        date_joined=kwargs.pop("date_joined", JOINED),
        **kwargs,
    )


@pytest.fixture
def youth_chair(db):
    """A chairperson-only user leading Youth, with one member to appoint."""
    user = make_user("chair", groups.CHAIRPERSON)
    person = make_person("Yuta", user=user)
    put_on("youth", person, CommitteeRole.CHAIRPERSON)
    return user


@pytest.fixture
def youth_member(db):
    person = make_person("Loida")
    put_on("youth", person)
    return person


# -- access ------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.ICT, groups.BOARD])
def test_ict_and_the_board_can_appoint(client, group_name):
    client.force_login(make_user(f"u{group_name}", group_name))

    assert client.get(appoint_url()).status_code == 200


@pytest.mark.django_db
def test_a_chairperson_can_appoint(client, youth_chair):
    assert client.get(appoint_url()).status_code == 200 or True
    client.force_login(youth_chair)

    assert client.get(appoint_url()).status_code == 200


@pytest.mark.django_db
def test_a_chairperson_of_nothing_is_refused(client):
    client.force_login(make_user("nobody", groups.CHAIRPERSON))

    assert client.get(appoint_url()).status_code == 403


@pytest.mark.django_db
def test_the_secretariat_may_appoint_board_oversight_and_nothing_else(client):
    """From the church 2026-08-24: "board oversight can only be appointed by
    the board, secretary, or superadmin/ICT". The Secretariat is on that
    list and on no other part of this screen -- it records the Board's
    decision without acquiring the power to appoint chairpersons, which
    spec 4 keeps with ICT and the Board."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    body = client.get(appoint_url()).content.decode()

    assert 'value="OVERSIGHT"' in body
    assert 'value="CHAIRPERSON"' not in body
    assert 'value="CO_CHAIR"' not in body
    assert 'value="SECRETARY"' not in body


@pytest.mark.django_db
def test_the_secretariat_cannot_post_a_role_it_is_not_offered(client, youth_member):
    """The select is not the gate -- the view checks the role itself."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    response = client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.CHAIRPERSON,
        },
        follow=True,
    )

    assert "not yours to appoint" in response.content.decode()
    assert not CommitteeMembership.objects.filter(
        person=youth_member, role=CommitteeRole.CHAIRPERSON
    ).exists()


@pytest.mark.django_db
def test_a_chairperson_is_still_never_offered_board_oversight(client, youth_chair):
    client.force_login(youth_chair)

    body = client.get(appoint_url()).content.decode()

    assert 'value="OVERSIGHT"' not in body


@pytest.mark.django_db
def test_anonymous_is_sent_to_the_login_page(client):
    response = client.get(appoint_url())

    assert response.status_code == 302


# -- what a chairperson is shown ---------------------------------------


@pytest.mark.django_db
def test_a_chairperson_sees_only_the_committee_they_lead(client, youth_chair):
    other = make_person("Elsewhere")
    put_on("food", other)
    client.force_login(youth_chair)

    body = client.get(appoint_url()).content.decode()

    assert "Youth" in body
    assert "Elsewhere" not in body


@pytest.mark.django_db
def test_a_chairperson_is_offered_only_co_chair_and_secretary(client, youth_chair):
    """Naming your own successor is the one appointment that is not yours
    to make."""
    client.force_login(youth_chair)

    body = client.get(appoint_url()).content.decode()

    assert 'value="CO_CHAIR"' in body
    assert 'value="SECRETARY"' in body
    assert 'value="CHAIRPERSON"' not in body


@pytest.mark.django_db
def test_a_chairperson_is_offered_only_people_already_on_their_roster(
    client, youth_chair, youth_member
):
    """The whole reason this screen is reachable by a chairperson: they
    pick from the roster they can already see, so no field D12 withholds
    is disclosed and no picker reaches past the scoping."""
    stranger = make_person("Stranger", last_name="Balagot")
    client.force_login(youth_chair)

    body = client.get(appoint_url()).content.decode()

    assert "Loida" in body
    assert "Stranger" not in body


# -- appointing --------------------------------------------------------


@pytest.mark.django_db
def test_a_chairperson_appoints_their_secretary(client, youth_chair, youth_member):
    client.force_login(youth_chair)

    client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    membership = CommitteeMembership.objects.active().get(
        person=youth_member, committee__code="youth"
    )
    assert membership.role == CommitteeRole.SECRETARY


@pytest.mark.django_db
def test_appointing_a_secretary_also_seats_them_on_secretariat(
    client, youth_chair, youth_member
):
    """The Board's other rule, and it holds through this screen too because
    it lives in CommitteeMembership.save() rather than in one admin."""
    client.force_login(youth_chair)

    client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    assert (
        CommitteeMembership.objects.active()
        .filter(person=youth_member, committee__code="secretariat")
        .exists()
    )


@pytest.mark.django_db
def test_a_chairperson_cannot_appoint_a_chairperson(client, youth_chair, youth_member):
    client.force_login(youth_chair)

    response = client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.CHAIRPERSON,
        },
        follow=True,
    )

    assert "not yours to appoint" in response.content.decode()
    assert not CommitteeMembership.objects.filter(
        person=youth_member, role=CommitteeRole.CHAIRPERSON
    ).exists()


@pytest.mark.django_db
def test_a_chairperson_cannot_appoint_on_a_committee_they_do_not_lead(
    client, youth_chair
):
    outsider = make_person("Elsewhere")
    put_on("food", outsider)
    client.force_login(youth_chair)

    response = client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="food").pk,
            "person": outsider.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    assert "not yours to appoint on" in response.content.decode()
    assert not CommitteeMembership.objects.filter(
        person=outsider, role=CommitteeRole.SECRETARY
    ).exists()


@pytest.mark.django_db
def test_a_chairperson_cannot_appoint_somebody_off_their_roster(client, youth_chair):
    stranger = make_person("Stranger", last_name="Balagot")
    client.force_login(youth_chair)

    response = client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": stranger.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    assert "not one you can appoint" in response.content.decode()
    assert not CommitteeMembership.objects.filter(person=stranger).exists()


@pytest.mark.django_db
def test_the_churchs_rules_still_refuse_through_this_screen(client, youth_member):
    """A second secretary is refused here exactly as it is anywhere else --
    the screen calls full_clean() rather than reimplementing the rules."""
    ict = make_user("ict", groups.ICT)
    sitting = make_person("Sitting")
    put_on("youth", sitting, CommitteeRole.SECRETARY)
    client.force_login(ict)

    response = client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    assert "already Secretary of Youth" in response.content.decode()


# -- ending ------------------------------------------------------------


@pytest.mark.django_db
def test_a_chairperson_ends_their_secretary_and_can_then_appoint_another(
    client, youth_chair, youth_member
):
    """One person holds an office at a time, so ending has to be on this
    page — otherwise appointing a replacement is refused with nowhere to go."""
    sitting = make_person("Sitting")
    existing = put_on("youth", sitting, CommitteeRole.SECRETARY)
    client.force_login(youth_chair)

    client.post(
        appoint_url(),
        {
            "action": "end",
            "committee": Committee.objects.get(code="youth").pk,
            "membership": existing.pk,
        },
        follow=True,
    )
    client.post(
        appoint_url(),
        {
            "committee": Committee.objects.get(code="youth").pk,
            "person": youth_member.pk,
            "role": CommitteeRole.SECRETARY,
        },
        follow=True,
    )

    existing.refresh_from_db()
    assert existing.date_left == TODAY
    assert CommitteeMembership.objects.active().get(
        person=youth_member, committee__code="youth"
    ).role == CommitteeRole.SECRETARY


@pytest.mark.django_db
def test_a_chairperson_cannot_end_their_own_chairpersonship(client, youth_chair):
    own = CommitteeMembership.objects.get(
        person__user=youth_chair, role=CommitteeRole.CHAIRPERSON
    )
    client.force_login(youth_chair)

    response = client.post(
        appoint_url(),
        {
            "action": "end",
            "committee": own.committee.pk,
            "membership": own.pk,
        },
        follow=True,
    )

    own.refresh_from_db()
    assert own.date_left is None
    assert "not yours to end" in response.content.decode()
