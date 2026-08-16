import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from committees.models import (
    Appointment,
    Committee,
    CommitteeFunction,
    CommitteeMembership,
    CommitteeRole,
    Position,
)
from people.models import Person

TODAY = timezone.localdate()
JOINED = TODAY - dt.timedelta(days=7)


@pytest.fixture
def person(db):
    return Person.objects.create(last_name="Malong", first_name="Shan")


def join(person, code, role=CommitteeRole.MEMBER):
    membership = CommitteeMembership(
        committee=Committee.objects.get(code=code),
        person=person,
        role=role,
        date_joined=JOINED,
    )
    membership.full_clean()
    membership.save()
    return membership


@pytest.mark.django_db
def test_a_person_may_join_two_committees(person):
    join(person, "ict")
    join(person, "events")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 2


@pytest.mark.django_db
def test_a_third_committee_is_refused(person):
    join(person, "ict")
    join(person, "events")
    with pytest.raises(ValidationError) as exc:
        join(person, "food")
    assert "two" in str(exc.value).lower()


@pytest.mark.django_db
def test_leaving_a_committee_frees_a_slot(person):
    first = join(person, "ict")
    join(person, "events")
    first.date_left = TODAY - dt.timedelta(days=1)
    first.save()
    join(person, "food")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 2


@pytest.mark.django_db
def test_being_chairperson_does_not_use_up_a_slot(person):
    """Spec section 3.3: otherwise chairing Grievance would block Diego elsewhere."""
    join(person, "grievance-and-reconciliation", role=CommitteeRole.CHAIRPERSON)
    join(person, "ict")
    join(person, "events")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 3


@pytest.mark.django_db
def test_only_one_chairperson_per_committee(person):
    other = Person.objects.create(last_name="Daclitan", first_name="Kathleen")
    join(person, "ict", role=CommitteeRole.CHAIRPERSON)
    with pytest.raises(ValidationError) as exc:
        join(other, "ict", role=CommitteeRole.CHAIRPERSON)
    assert "chairperson" in str(exc.value).lower()


@pytest.mark.django_db
def test_a_function_must_belong_to_its_own_committee(person):
    transport = CommitteeFunction.objects.get(name="Transport")
    membership = CommitteeMembership(
        committee=Committee.objects.get(code="ict"),
        person=person,
        function=transport,
        role=CommitteeRole.MEMBER,
        date_joined=JOINED,
    )
    with pytest.raises(ValidationError):
        membership.full_clean()


@pytest.mark.django_db
def test_oversight_requires_a_board_appointment(person):
    with pytest.raises(ValidationError) as exc:
        join(person, "ict", role=CommitteeRole.OVERSIGHT)
    assert "board" in str(exc.value).lower()

    Appointment.objects.create(
        person=person,
        position=Position.objects.get(code="board-member"),
        start_date=dt.date(2026, 1, 1),
    )
    join(person, "ict", role=CommitteeRole.OVERSIGHT)
    assert CommitteeMembership.objects.filter(role=CommitteeRole.OVERSIGHT).count() == 1


@pytest.mark.django_db
def test_a_future_departure_does_not_free_a_slot_early(person):
    join(person, "ict")
    join(person, "events")
    third = CommitteeMembership(
        committee=Committee.objects.get(code="food"),
        person=person,
        role=CommitteeRole.MEMBER,
        date_joined=JOINED,
        date_left=TODAY + dt.timedelta(days=30),
    )
    with pytest.raises(ValidationError):
        third.full_clean()


@pytest.mark.django_db
def test_a_date_left_before_date_joined_is_rejected(person):
    """Gap 1: a transposed date must not create a row that active() treats
    as not-yet-started and _has_ended() treats as already-over at the same
    time -- exempt from both the two-committee cap and the one-chairperson
    rule, and invisible on every active roster.
    """
    backwards = CommitteeMembership(
        committee=Committee.objects.get(code="ict"),
        person=person,
        role=CommitteeRole.MEMBER,
        date_joined=TODAY,
        date_left=TODAY - dt.timedelta(days=10),
    )
    with pytest.raises(ValidationError) as exc:
        backwards.full_clean()
    assert "precede" in str(exc.value).lower()


@pytest.mark.django_db
def test_a_same_day_join_and_leave_is_permitted(person):
    """Same-day is a real, zero-duration membership, not the typo the
    ordering check exists to catch: active() already treats a membership
    ending today as active today, so date_joined == date_left is not
    'reversed' and must be accepted.
    """
    same_day = CommitteeMembership(
        committee=Committee.objects.get(code="ict"),
        person=person,
        role=CommitteeRole.MEMBER,
        date_joined=JOINED,
        date_left=JOINED,
    )
    same_day.full_clean()
    same_day.save()
    assert CommitteeMembership.objects.active(on=JOINED).filter(pk=same_day.pk).exists()
    assert not (
        CommitteeMembership.objects.active(on=JOINED + dt.timedelta(days=1))
        .filter(pk=same_day.pk)
        .exists()
    )


@pytest.mark.django_db
def test_a_future_departure_does_not_permit_a_second_chairperson(person):
    other = Person.objects.create(last_name="Daclitan", first_name="Kathleen")
    join(person, "ict", role=CommitteeRole.CHAIRPERSON)
    clash = CommitteeMembership(
        committee=Committee.objects.get(code="ict"),
        person=other,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED,
        date_left=TODAY + dt.timedelta(days=30),
    )
    with pytest.raises(ValidationError):
        clash.full_clean()
