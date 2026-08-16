"""Whole-branch audit fixes to the five role groups' permissions.

Does NOT touch 0002_create_groups.py -- that migration is already applied to a
live production database. This is a new forward migration layered on top of it.
Fixes three gaps found against docs/superpowers/specs/2026-08-16-aeci-people-
committees-design.md section 4 (the "permission matrix IS the test suite", per
section 9):

* Gap 1 -- ICT's "__all__" grant in 0002_create_groups was evaluated against
  the model registry as it stood when that migration ran, which was BEFORE
  records.PurgeRecord existed (added two migrations later, by
  records.0003_purgerecord). No group has ever held any PurgeRecord
  permission, including ICT and the Board -- the only two groups the design
  gives read access to purge evidence, which is the sole surviving proof a
  contact-data purge happened once the change history and scanned form image
  are gone (spec section 5.1). Re-running the same "__all__" query here, after
  records.0004, catches PurgeRecord and would catch any other model added to
  these apps between 0002 and this migration in the same pass -- there
  happens to be exactly one such model today. add/change/delete on
  PurgeRecord are deliberately excluded even from ICT's normally-total grant:
  records.admin.PurgeRecordAdmin hardcodes those three has_*_permission()
  checks to False for every user, so granting the underlying Permission would
  only make a group's permission set claim a capability the admin can never
  honour.

* Gap 2 -- spec section 4's matrix grants Board "Set status -> MEMBER", but
  0002_create_groups never granted Board change_person, so a Board member
  could view a Person record but not save an acceptance into membership.
  Granting it here. change_person is a model-wide Django permission with no
  field-level granularity, so this also lets a Board member edit every other
  Person field through the admin (people/admin.py's PersonAdmin restricts
  fields only for chairperson-only users, not for Board) -- wider than the
  matrix's single checked cell for Board. See fix-perms-report.md for the
  full reasoning; people/admin.py is out of scope for this migration.

* Gap 3 -- verified against people/models.py and 0002_create_groups before
  changing anything: HouseholdMember.household has on_delete=CASCADE, and
  HouseholdMember carries no django-simple-history trail (unlike Person,
  Appointment and CommitteeMembership, which do), so deleting a Household
  silently and unrecoverably destroys its member rows. The design's matrix
  reserves "Hard-delete anything" to ICT alone, with no asterisk exception for
  Secretariat (unlike the Set-status-to-MEMBER row). Revoking
  delete_household and delete_householdmember from Secretariat.
  add_household/change_household/add_householdmember/change_householdmember
  are untouched, so ordinary encoding corrections (fixing a name, a role, an
  address) are unaffected -- only outright row removal now requires ICT,
  matching "[hard delete] exists solely for genuine mistakes such as a
  duplicated row."

Gap 4 -- non-destructive reverse: 0002_create_groups' reverse deletes the
Group rows outright, which silently strips every user's role assignment. This
migration's reverse only ever adjusts permission membership on groups that
continue to exist, restoring each group to its pre-migration shape.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

APP_LABELS = ("people", "committees", "records", "core")

# records.admin.PurgeRecordAdmin hardcodes has_add/change/delete_permission to
# False for every user, so granting the underlying Django permission for any
# of these three would claim a capability the admin never honours. Excluded
# even from ICT's otherwise-total "__all__" grant for that reason.
PURGE_RECORD_WRITE_CODENAMES = (
    "add_purgerecord",
    "change_purgerecord",
    "delete_purgerecord",
)
# All four -- used only to restore ICT to its pre-migration (pre-PurgeRecord)
# shape on reverse, since PurgeRecord did not exist when 0002 ran.
PURGE_RECORD_ALL_CODENAMES = PURGE_RECORD_WRITE_CODENAMES + ("view_purgerecord",)


def _ensure_permissions_exist(apps):
    # Mirrors 0002_create_groups (see its own comment and Task 9's report for
    # why): Permission rows are normally created by the post_migrate signal,
    # which fires once, after every migration in a run has applied. On a
    # fresh database -- pytest-django's test DB, or a from-scratch `migrate`
    # -- that signal has not fired yet when this RunPython step executes, so
    # the queries below would find nothing to grant or revoke unless
    # permission creation is forced now, against the historical (frozen) app
    # registry.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, verbosity=0, apps=apps)
        app_config.models_module = None


def fix_permissions(apps, schema_editor):
    _ensure_permissions_exist(apps)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # Gap 1: re-evaluate ICT's "__all__" against the CURRENT model registry
    # (i.e. as of this migration) instead of relying on the stale snapshot
    # 0002 computed. This is the systemic fix, not a one-off grant: it is the
    # same query 0002 used, just re-run later in migration history, so it
    # picks up PurgeRecord (and would pick up any sibling model added since)
    # automatically.
    ict = Group.objects.get(name="ICT")
    ict.permissions.set(
        Permission.objects.filter(
            content_type__app_label__in=APP_LABELS + ("auth",)
        ).exclude(codename__in=PURGE_RECORD_WRITE_CODENAMES)
    )

    # Gap 1: Board reads purge evidence too (view only).
    # Gap 2: Board records an acceptance into membership (spec section 4).
    board = Group.objects.get(name="Board")
    board.permissions.add(
        Permission.objects.get(
            codename="view_purgerecord", content_type__app_label="records"
        ),
        Permission.objects.get(
            codename="change_person", content_type__app_label="people"
        ),
    )

    # Gap 3: hard delete of Household/HouseholdMember reserved to ICT -- see
    # module docstring.
    secretariat = Group.objects.get(name="Secretariat")
    secretariat.permissions.remove(
        Permission.objects.get(
            codename="delete_household", content_type__app_label="people"
        ),
        Permission.objects.get(
            codename="delete_householdmember", content_type__app_label="people"
        ),
    )


def restore_permissions(apps, schema_editor):
    # Non-destructive (Gap 4): adjusts permission membership only, never
    # deletes a Group or touches user-group assignments.
    _ensure_permissions_exist(apps)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    ict = Group.objects.get(name="ICT")
    ict.permissions.set(
        Permission.objects.filter(
            content_type__app_label__in=APP_LABELS + ("auth",)
        ).exclude(codename__in=PURGE_RECORD_ALL_CODENAMES)
    )

    board = Group.objects.get(name="Board")
    board.permissions.remove(
        Permission.objects.get(
            codename="view_purgerecord", content_type__app_label="records"
        ),
        Permission.objects.get(
            codename="change_person", content_type__app_label="people"
        ),
    )

    secretariat = Group.objects.get(name="Secretariat")
    secretariat.permissions.add(
        Permission.objects.get(
            codename="delete_household", content_type__app_label="people"
        ),
        Permission.objects.get(
            codename="delete_householdmember", content_type__app_label="people"
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_enforce_unique_perpetual_sequence"),
        ("people", "0002_household_householdmember"),
        ("committees", "0004_committeemembership_historicalcommitteemembership"),
        ("records", "0004_purgerecord_scan_files_removed"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(fix_permissions, restore_permissions)]
