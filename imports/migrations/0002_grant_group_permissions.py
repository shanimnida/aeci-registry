"""Grants ICT and Secretariat permission on this new app.

Mirrors core/migrations/0004_fix_group_permissions.py's Gap 1 fix exactly,
for the same underlying reason: core/migrations/0002_create_groups.py's
ICT "__all__" grant and 0004's re-run of it were both evaluated against the
model registry as it stood at the time, which was before this app existed.
Without this migration, ICT -- "the system administrator role" per
docs/superpowers/specs/2026-08-16-aeci-people-committees-design.md section 4
-- would hold no permission at all on the import workflow, despite the
group's whole point being a total grant. Using an additive .add() rather
than the historical-registry-wide .set() 0004 uses: this migration only
needs to add the app that is new since then, not re-derive the group's
entire permission set.

Secretariat gets the operational subset the review screens actually check
(imports/admin.py's _require_reviewer calls): stage a file, see progress,
and decide on a row. Individual StagedPerson rows are never deleted on
their own -- only a whole batch is (which is safe: StagedPerson.batch is
CASCADE, but StagedPerson.created_person is SET_NULL, so deleting a batch
never touches an already-approved Person) -- so delete_stagedperson is
granted to neither group, matching the append-only shape of the staging
model.

The Chairperson group is untouched: neither group in this migration is
Chairperson, so a chairperson-only user gets no permission here, which is
what tests/imports/test_scoping.py checks for.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

SECRETARIAT_CODENAMES = (
    "add_importbatch", "view_importbatch", "delete_importbatch",
    "add_stagedperson", "view_stagedperson", "change_stagedperson",
)


def _ensure_permissions_exist(apps):
    # Same reasoning as core/migrations/0002_create_groups.py and 0004: the
    # post_migrate signal that normally creates Permission rows fires once,
    # after every migration in a run has applied, so on a fresh database it
    # has not fired yet when this RunPython step executes.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, verbosity=0, apps=apps)
        app_config.models_module = None


def grant_permissions(apps, schema_editor):
    _ensure_permissions_exist(apps)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    ict = Group.objects.get(name="ICT")
    ict.permissions.add(*Permission.objects.filter(content_type__app_label="imports"))

    secretariat = Group.objects.get(name="Secretariat")
    secretariat.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="imports", codename__in=SECRETARIAT_CODENAMES
        )
    )


def revoke_permissions(apps, schema_editor):
    _ensure_permissions_exist(apps)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    ict = Group.objects.get(name="ICT")
    ict.permissions.remove(*Permission.objects.filter(content_type__app_label="imports"))

    secretariat = Group.objects.get(name="Secretariat")
    secretariat.permissions.remove(
        *Permission.objects.filter(content_type__app_label="imports")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0001_initial"),
        ("core", "0004_fix_group_permissions"),
    ]

    operations = [migrations.RunPython(grant_permissions, revoke_permissions)]
