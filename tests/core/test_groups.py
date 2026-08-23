import pytest
from django.contrib.auth.models import Group, Permission

from core import groups

# Mirrors core/migrations/0004_fix_group_permissions.py's own constants,
# deliberately duplicated rather than imported -- migrations are not meant to
# be imported as regular modules, and a test that imports the fix would not
# notice if the fix and the test drifted apart in the same direction.
# "imports" added by imports/migrations/0002_grant_group_permissions.py --
# the same Gap 1 shape one app label later: a fresh app has no permission
# rows until create_permissions runs, so ICT's "__all__" grant has to be
# re-evaluated (there or here) every time a new app joins this list.
APP_LABELS = ("people", "committees", "records", "core", "imports")
PURGE_RECORD_WRITE_CODENAMES = ("add_purgerecord", "change_purgerecord", "delete_purgerecord")


def _codenames(group_name):
    return set(
        Group.objects.get(name=group_name).permissions.values_list("codename", flat=True)
    )


@pytest.mark.django_db
def test_all_five_groups_exist():
    assert set(Group.objects.values_list("name", flat=True)) == set(groups.ALL_GROUPS)


@pytest.mark.django_db
def test_ict_holds_every_permission_in_its_apps_except_purge_record_writes():
    """Gap 1 of the 2026-08-16 whole-branch audit: 0002_create_groups granted
    ICT "__all__", evaluated once when that migration ran -- before
    records.PurgeRecord existed. No group held any PurgeRecord permission at
    all afterwards, including ICT, though ICT's grant was meant to be total.

    Asserted as an invariant (everything in these apps except the three
    PurgeRecord write codenames) rather than a hardcoded codename list, so
    this test does not go stale the same way the migration it is checking
    once did -- a future model in one of these apps is automatically expected
    here too.
    """
    expected = set(
        Permission.objects.filter(content_type__app_label__in=APP_LABELS + ("auth",))
        .exclude(codename__in=PURGE_RECORD_WRITE_CODENAMES)
        .values_list("codename", flat=True)
    )
    actual = _codenames(groups.ICT)
    assert actual == expected
    # Sanity check against a vacuous pass (e.g. both sides accidentally empty).
    assert "delete_person" in actual
    assert "add_user" in actual
    assert "view_purgerecord" in actual


@pytest.mark.django_db
def test_secretariat_permissions_exact():
    assert _codenames(groups.SECRETARIAT) == {
        "add_person", "change_person", "view_person",
        "add_household", "change_household", "view_household",
        "add_householdmember", "change_householdmember", "view_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "view_position", "view_appointment",
        "add_formscan", "change_formscan", "view_formscan",
        "add_importbatch", "view_importbatch", "delete_importbatch",
        "add_stagedperson", "view_stagedperson", "change_stagedperson",
    }


@pytest.mark.django_db
def test_secretariat_can_edit_people_but_not_create_logins():
    codenames = _codenames(groups.SECRETARIAT)
    assert "change_person" in codenames
    assert "add_person" in codenames
    assert "delete_person" not in codenames
    assert "add_user" not in codenames


@pytest.mark.django_db
def test_secretariat_cannot_delete_a_household_or_its_members():
    """Gap 3: deleting a Household cascades (on_delete=CASCADE) to
    HouseholdMember, which -- unlike Person, Appointment and
    CommitteeMembership -- carries no django-simple-history trail, so the
    deletion is silent and unrecoverable. The design's matrix reserves
    "Hard-delete anything" to ICT alone. Secretariat keeps the ability to
    correct encoding mistakes by editing rows in place.
    """
    codenames = _codenames(groups.SECRETARIAT)
    assert "delete_household" not in codenames
    assert "delete_householdmember" not in codenames
    assert "change_household" in codenames
    assert "change_householdmember" in codenames


@pytest.mark.django_db
def test_ict_can_create_logins_but_the_board_cannot():
    ict = _codenames(groups.ICT)
    board = _codenames(groups.BOARD)
    assert "add_user" in ict
    assert "add_user" not in board


@pytest.mark.django_db
def test_nobody_but_ict_may_delete_a_person():
    """Spec section 4: deletion is a status change, not a row removal."""
    for name in (groups.SECRETARIAT, groups.BOARD, groups.CHAIRPERSON):
        assert "delete_person" not in _codenames(name)
    assert "delete_person" in _codenames(groups.ICT)


@pytest.mark.django_db
def test_board_permissions_exact():
    assert _codenames(groups.BOARD) == {
        "view_person",
        "view_household", "view_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "add_appointment", "change_appointment", "view_appointment",
        "view_position",
        "view_accesslog",
        "view_purgerecord",
        "change_person",
    }


@pytest.mark.django_db
def test_board_can_record_a_membership_acceptance():
    """Gap 2: spec section 4's matrix checks Board for 'Set status ->
    MEMBER'. Without change_person a Board member could view a Person record
    but never save an acceptance into membership."""
    assert "change_person" in _codenames(groups.BOARD)


@pytest.mark.django_db
def test_chairpersons_may_only_view_people():
    assert _codenames(groups.CHAIRPERSON) == {
        "view_person", "view_committee", "view_committeemembership"
    }


@pytest.mark.django_db
def test_the_treasurer_group_no_longer_exists():
    """It was created empty, reserved for a finance subsystem. Removed
    2026-08-24: the Treasurer has not asked for anything, so that subsystem
    is not merely unbuilt but unconfirmed, and a group granting nothing is a
    checkbox on the account form that quietly does nothing.

    The Treasurer POSITION -- the church office whose appointments are
    recorded -- is a different thing and still seeded; see
    test_the_treasurer_office_itself_still_exists below."""
    assert not Group.objects.filter(name="Treasurer").exists()
    assert "Treasurer" not in groups.ALL_GROUPS


@pytest.mark.django_db
def test_the_treasurer_office_itself_still_exists():
    """Removing the login group must not remove the church office. The
    Treasurer is a real officer and their appointments are part of the
    corporate record (spec 7.6)."""
    from committees.models import Position

    assert Position.objects.filter(code="treasurer").exists()


@pytest.mark.django_db
def test_purge_record_is_readable_only_by_ict_and_board():
    """Gap 1: PurgeRecord is the durable evidence a purge occurred (spec
    section 5.1) -- the only proof left once the change history is scrubbed
    and the scanned form image is deleted. It must be visible to ICT and the
    Board, and to nobody else, not even Secretariat, which manages the
    records being purged.
    """
    for name in groups.ALL_GROUPS:
        codenames = _codenames(name)
        if name in (groups.ICT, groups.BOARD):
            assert "view_purgerecord" in codenames, name
        else:
            assert "view_purgerecord" not in codenames, name


@pytest.mark.django_db
def test_nobody_holds_add_change_or_delete_on_purge_record():
    """records.admin.PurgeRecordAdmin hardcodes add/change/delete to False
    for everyone, so the permission set should agree with the admin rather
    than contradict it -- not even ICT, whose grant is otherwise total."""
    for name in groups.ALL_GROUPS:
        codenames = _codenames(name)
        assert "add_purgerecord" not in codenames, name
        assert "change_purgerecord" not in codenames, name
        assert "delete_purgerecord" not in codenames, name


@pytest.mark.django_db
def test_no_non_ict_group_can_both_create_a_login_and_grant_membership():
    """Spec section 4: 'Separation of duties ... Neither role can
    unilaterally manufacture a member.' ICT is the system's technical
    administrator group -- matrix-sanctioned to hold both add_user and
    change_person, alongside hard-delete and management of every model in
    these apps -- so it is deliberately excluded here. The separation the
    design is protecting is among the other four: none of them may create a
    login at all, so none of them can pair that with granting membership.
    """
    for name in (groups.SECRETARIAT, groups.BOARD, groups.CHAIRPERSON):
        codenames = _codenames(name)
        assert not ("add_user" in codenames and "change_person" in codenames), name
