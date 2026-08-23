"""A Secretary office on every committee, requested 2026-08-23.

Two roles arrive together, and the second is not decoration. A committee
secretary sits on the Secretariat committee by virtue of their office, and
that membership must not be counted as one of the two committees the
profiling form asks a member to volunteer for -- otherwise anyone who
ticked two boxes AND holds a secretary post trips the overflow warning the
moment they are recorded, every time. `EX_OFFICIO` is what that membership
is: on this committee because of an office, not because they volunteered.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.utils import timezone
from django.core.exceptions import ValidationError

from committees.models import Committee, CommitteeMembership, CommitteeRole
from people.models import MembershipStatus, Person

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=30)


@pytest.fixture
def person(db):
    return Person.objects.create(
        last_name="Baguilat", first_name="Imelda", membership_status=MembershipStatus.MEMBER
    )


def membership(committee_code, person, role, **kwargs):
    return CommitteeMembership(
        committee=Committee.objects.get(code=committee_code),
        person=person,
        role=role,
        date_joined=kwargs.pop("date_joined", JOINED),
        **kwargs,
    )


# -- the role exists ----------------------------------------------------


@pytest.mark.django_db
def test_a_person_can_be_recorded_as_a_committee_secretary(person):
    entry = membership("youth", person, CommitteeRole.SECRETARY)
    entry.full_clean()
    entry.save()

    assert entry.get_role_display() == "Secretary"
    assert entry.is_active


# -- one secretary per committee, hard (mirrors the chairperson rule) ---


@pytest.mark.django_db
def test_a_second_active_secretary_on_one_committee_is_refused(person):
    membership("youth", person, CommitteeRole.SECRETARY).save()
    other = Person.objects.create(last_name="Dulnuan", first_name="Randy")

    with pytest.raises(ValidationError) as exc:
        membership("youth", other, CommitteeRole.SECRETARY).full_clean()

    assert "secretary" in str(exc.value).lower()


@pytest.mark.django_db
def test_a_secretary_on_a_different_committee_is_fine(person):
    membership("youth", person, CommitteeRole.SECRETARY).save()
    other = Person.objects.create(last_name="Dulnuan", first_name="Randy")

    entry = membership("food", other, CommitteeRole.SECRETARY)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_a_secretary_whose_term_ended_frees_the_post(person):
    membership(
        "youth", person, CommitteeRole.SECRETARY,
        date_joined=TODAY - dt.timedelta(days=90),
        date_left=TODAY - dt.timedelta(days=1),
    ).save()
    other = Person.objects.create(last_name="Dulnuan", first_name="Randy")

    entry = membership("youth", other, CommitteeRole.SECRETARY)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_a_future_departure_does_not_free_the_post_early(person):
    """_has_ended()'s guard, same as R12 established for chairpersons: a
    membership scheduled to end next month is active now."""
    membership(
        "youth", person, CommitteeRole.SECRETARY, date_left=TODAY + dt.timedelta(days=30)
    ).save()
    other = Person.objects.create(last_name="Dulnuan", first_name="Randy")

    with pytest.raises(ValidationError):
        membership("youth", other, CommitteeRole.SECRETARY).full_clean()


# -- neither new role eats a volunteered slot ---------------------------


@pytest.mark.django_db
def test_being_a_secretary_does_not_consume_a_self_selected_slot(person):
    """The form's "select up to TWO (2)" is about what you volunteer for,
    not what you are appointed to -- same reasoning that exempts chairing."""
    membership("sunshine", person, CommitteeRole.MEMBER).save()
    membership("food", person, CommitteeRole.MEMBER).save()

    entry = membership("youth", person, CommitteeRole.SECRETARY)
    entry.save()

    assert entry.self_selected_overflow_count() is None


@pytest.mark.django_db
def test_the_ex_officio_seat_on_secretariat_does_not_consume_a_slot_either(person):
    """The case that decided this. Two ticked committees plus the
    Secretariat seat that follows from being a secretary would otherwise
    read as three, and warn every single time."""
    membership("sunshine", person, CommitteeRole.MEMBER).save()
    membership("food", person, CommitteeRole.MEMBER).save()
    # The Secretariat seat is created by this save, not by hand.
    membership("youth", person, CommitteeRole.SECRETARY).save()

    seat = CommitteeMembership.objects.active().get(
        person=person, committee__code="secretariat"
    )
    assert seat.role == CommitteeRole.EX_OFFICIO
    assert seat.self_selected_overflow_count() is None
    volunteered = CommitteeMembership.objects.active().filter(
        person=person, role=CommitteeRole.MEMBER
    )
    assert volunteered.count() == 2


@pytest.mark.django_db
def test_a_third_genuinely_volunteered_committee_still_warns(person):
    """The exemptions must not disarm the warning for what it is actually
    for -- someone who really did tick three boxes."""
    membership("sunshine", person, CommitteeRole.MEMBER).save()
    membership("food", person, CommitteeRole.MEMBER).save()
    membership("youth", person, CommitteeRole.SECRETARY).save()

    third = membership("events", person, CommitteeRole.MEMBER)
    third.save()

    assert third.self_selected_overflow_count() == 3


@pytest.mark.django_db
def test_several_committees_secretaries_can_all_sit_on_secretariat(person):
    """Twelve secretaries, one Secretariat committee. EX_OFFICIO carries no
    uniqueness rule -- unlike Secretary and Chairperson, it is not an
    office, it is a seat."""
    second = Person.objects.create(last_name="Dulnuan", first_name="Randy")
    for holder in (person, second):
        seat = membership("secretariat", holder, CommitteeRole.EX_OFFICIO)
        seat.full_clean()
        seat.save()

    assert (
        CommitteeMembership.objects.active()
        .filter(committee__code="secretariat", role=CommitteeRole.EX_OFFICIO)
        .count()
        == 2
    )


# -- the prompt (the "also on Secretariat" rule) ------------------------


@pytest.fixture
def secretariat_user(db):
    from django.contrib.auth.models import Group, User

    from core import groups

    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.ICT))
    return user


def add_membership_via_admin(client, committee_code, person, role):
    from django.urls import reverse

    return client.post(
        reverse("admin:committees_committeemembership_add"),
        {
            "committee": Committee.objects.get(code=committee_code).pk,
            "person": person.pk,
            "role": role,
            "date_joined": JOINED.isoformat(),
            "date_left": "",
            "function": "",
        },
        follow=True,
    )


@pytest.mark.django_db
def test_recording_a_secretary_seats_them_on_secretariat_automatically(person):
    """The Board's rule: every committee secretary IS a member of the
    Secretariat committee. Not a discretion exercised person by person, so
    AEGIS records it rather than asking."""
    membership("youth", person, CommitteeRole.SECRETARY).save()

    seat = CommitteeMembership.objects.active().get(
        person=person, committee__code="secretariat"
    )
    assert seat.role == CommitteeRole.EX_OFFICIO
    assert seat.date_joined == JOINED


@pytest.mark.django_db
def test_the_seat_is_not_duplicated_on_a_second_save(person):
    entry = membership("youth", person, CommitteeRole.SECRETARY)
    entry.save()
    entry.save()

    assert (
        CommitteeMembership.objects.filter(
            person=person, committee__code="secretariat"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_ending_the_secretary_post_ends_the_seat_on_the_day_it_ended(person):
    entry = membership("youth", person, CommitteeRole.SECRETARY)
    entry.save()
    ended = TODAY - dt.timedelta(days=2)

    entry.date_left = ended
    entry.save()

    seat = CommitteeMembership.objects.get(person=person, committee__code="secretariat")
    # The day the post ended, not today -- the service record has to read
    # truthfully.
    assert seat.date_left == ended
    assert not seat.is_active


@pytest.mark.django_db
def test_a_second_secretary_post_keeps_the_seat_when_the_first_ends(person):
    """One person may keep the minutes for two committees. Losing one post
    must not un-seat them while they still hold the other."""
    first = membership("youth", person, CommitteeRole.SECRETARY)
    first.save()
    membership("food", person, CommitteeRole.SECRETARY).save()

    first.date_left = TODAY - dt.timedelta(days=1)
    first.save()

    seat = CommitteeMembership.objects.get(person=person, committee__code="secretariat")
    assert seat.is_active


@pytest.mark.django_db
def test_a_volunteered_secretariat_membership_is_never_ended_by_this(person):
    """Losing a secretary post must not quietly cancel a committee they
    chose to serve on. Only the EX_OFFICIO seat is AEGIS's to manage."""
    membership("secretariat", person, CommitteeRole.MEMBER).save()
    entry = membership("youth", person, CommitteeRole.SECRETARY)
    entry.save()

    entry.date_left = TODAY - dt.timedelta(days=1)
    entry.save()

    volunteered = CommitteeMembership.objects.get(
        person=person, committee__code="secretariat", role=CommitteeRole.MEMBER
    )
    assert volunteered.is_active


@pytest.mark.django_db
def test_the_secretariats_own_secretary_gets_no_extra_seat(person):
    membership("secretariat", person, CommitteeRole.SECRETARY).save()

    assert (
        CommitteeMembership.objects.filter(
            person=person, committee__code="secretariat"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_the_admin_says_the_seat_was_recorded(client, secretariat_user, person):
    client.force_login(secretariat_user)

    response = add_membership_via_admin(client, "youth", person, CommitteeRole.SECRETARY)

    assert "also sits on the Secretariat committee, recorded automatically" in (
        response.content.decode()
    )


@pytest.mark.django_db
def test_the_overview_flags_a_committee_with_no_secretary(client, secretariat_user, person):
    from django.urls import reverse

    membership("youth", person, CommitteeRole.CHAIRPERSON).save()
    client.force_login(secretariat_user)

    body = client.get(
        reverse("admin:committees_committeemembership_overview")
    ).content.decode()

    assert "No secretary assigned" in body


# -- one role per committee ---------------------------------------------


@pytest.mark.django_db
def test_a_chairperson_cannot_also_be_marked_a_member_of_the_same_committee(person):
    """Found in real data: the same person down as both Chairperson and
    Member of Food. Chairing a committee is a way of being on it, not a
    second thing you do there."""
    membership("food", person, CommitteeRole.CHAIRPERSON).save()

    with pytest.raises(ValidationError) as exc:
        membership("food", person, CommitteeRole.MEMBER).full_clean()

    assert "already Chairperson of Food" in str(exc.value)


@pytest.mark.django_db
def test_the_same_person_may_serve_on_two_different_committees(person):
    membership("food", person, CommitteeRole.CHAIRPERSON).save()

    entry = membership("youth", person, CommitteeRole.MEMBER)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_rejoining_a_committee_after_leaving_is_still_allowed(person):
    """Serving, leaving and later coming back is ordinary, and the history
    of it has to stay recordable -- which is why this is a rule about
    ACTIVE memberships rather than a database constraint."""
    membership(
        "food", person, CommitteeRole.MEMBER,
        date_joined=TODAY - dt.timedelta(days=400),
        date_left=TODAY - dt.timedelta(days=200),
    ).save()

    entry = membership("food", person, CommitteeRole.MEMBER)
    entry.full_clean()  # must not raise


@pytest.mark.django_db
def test_a_volunteer_for_secretariat_gets_no_second_ex_officio_row(person):
    """The case this fix introduced: someone who ticked Secretariat on
    their form is already on it, so a secretary post must not put them on
    the same roster twice."""
    membership("secretariat", person, CommitteeRole.MEMBER).save()

    membership("youth", person, CommitteeRole.SECRETARY).save()

    rows = CommitteeMembership.objects.active().filter(
        person=person, committee__code="secretariat"
    )
    assert rows.count() == 1
    assert rows.get().role == CommitteeRole.MEMBER
