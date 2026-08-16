import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from committees.models import Appointment, Position
from people.models import Person


@pytest.fixture
def treasurer_position(db):
    return Position.objects.get(code="treasurer")


@pytest.mark.django_db
def test_positions_are_seeded():
    assert Position.objects.count() == 5
    assert Position.objects.get(code="treasurer").is_unique_holder is True
    assert Position.objects.get(code="board-member").is_unique_holder is False


@pytest.mark.django_db
def test_two_people_cannot_hold_a_unique_position_at_once(treasurer_position):
    first = Person.objects.create(last_name="Fredalyn", first_name="A")
    second = Person.objects.create(last_name="Juliet", first_name="B")
    Appointment.objects.create(
        person=first, position=treasurer_position, start_date=dt.date(2026, 1, 1)
    )
    clash = Appointment(
        person=second, position=treasurer_position, start_date=dt.date(2026, 6, 1)
    )
    with pytest.raises(ValidationError):
        clash.full_clean()


@pytest.mark.django_db
def test_a_successor_may_start_after_the_previous_holder_ends(treasurer_position):
    first = Person.objects.create(last_name="Fredalyn", first_name="A")
    second = Person.objects.create(last_name="Juliet", first_name="B")
    Appointment.objects.create(
        person=first,
        position=treasurer_position,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 12, 31),
    )
    successor = Appointment(
        person=second, position=treasurer_position, start_date=dt.date(2026, 1, 1)
    )
    successor.full_clean()
    successor.save()
    assert Appointment.objects.count() == 2


@pytest.mark.django_db
def test_several_people_may_be_board_members_at_once():
    board_member = Position.objects.get(code="board-member")
    for name in ("Diego", "Jemuel", "Sonia"):
        person = Person.objects.create(last_name=name, first_name="X")
        appointment = Appointment(
            person=person, position=board_member, start_date=dt.date(2026, 1, 1)
        )
        appointment.full_clean()
        appointment.save()
    assert Appointment.objects.count() == 3
