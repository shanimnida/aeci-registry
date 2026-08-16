import pytest
from django.contrib.auth.models import Group

from core import groups


@pytest.mark.django_db
def test_all_five_groups_exist():
    assert set(Group.objects.values_list("name", flat=True)) == set(groups.ALL_GROUPS)


@pytest.mark.django_db
def test_secretariat_can_edit_people_but_not_create_logins():
    codenames = set(
        Group.objects.get(name=groups.SECRETARIAT)
        .permissions.values_list("codename", flat=True)
    )
    assert "change_person" in codenames
    assert "add_person" in codenames
    assert "delete_person" not in codenames
    assert "add_user" not in codenames


@pytest.mark.django_db
def test_ict_can_create_logins_but_the_board_cannot():
    ict = set(
        Group.objects.get(name=groups.ICT).permissions.values_list("codename", flat=True)
    )
    board = set(
        Group.objects.get(name=groups.BOARD).permissions.values_list("codename", flat=True)
    )
    assert "add_user" in ict
    assert "add_user" not in board


@pytest.mark.django_db
def test_nobody_but_ict_may_delete_a_person():
    """Spec section 4: deletion is a status change, not a row removal."""
    for name in (groups.SECRETARIAT, groups.BOARD, groups.CHAIRPERSON, groups.TREASURER):
        codenames = set(
            Group.objects.get(name=name).permissions.values_list("codename", flat=True)
        )
        assert "delete_person" not in codenames
    ict = set(
        Group.objects.get(name=groups.ICT).permissions.values_list("codename", flat=True)
    )
    assert "delete_person" in ict


@pytest.mark.django_db
def test_chairpersons_may_only_view_people():
    codenames = set(
        Group.objects.get(name=groups.CHAIRPERSON)
        .permissions.values_list("codename", flat=True)
    )
    assert codenames == {"view_person", "view_committee", "view_committeemembership"}


@pytest.mark.django_db
def test_the_treasurer_group_is_empty_in_phase_a():
    """Spec section 4: the Treasurer's work lives in Phases B and C."""
    assert Group.objects.get(name=groups.TREASURER).permissions.count() == 0
