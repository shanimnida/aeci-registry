from django.contrib.auth.management import create_permissions
from django.db import migrations

# Spec section 4. Treasurer is intentionally empty in Phase A: fund release,
# OR numbers and the ledger are Phases B and C. The group is created now so
# accounts and memberships are in place before those subsystems land.
GROUP_PERMISSIONS = {
    "ICT": "__all__",
    "Secretariat": [
        "add_person", "change_person", "view_person",
        "add_household", "change_household", "view_household", "delete_household",
        "add_householdmember", "change_householdmember", "view_householdmember",
        "delete_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "view_position", "view_appointment",
        "add_formscan", "change_formscan", "view_formscan",
    ],
    "Treasurer": [],
    "Board": [
        "view_person",
        "view_household", "view_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "add_appointment", "change_appointment", "view_appointment",
        "view_position",
        "view_accesslog",
    ],
    "Chairperson": ["view_person", "view_committee", "view_committeemembership"],
}

APP_LABELS = ("people", "committees", "records", "core")


def create_groups(apps, schema_editor):
    # Permission rows are normally created by the post_migrate signal, which
    # only fires after *every* migration in this run has applied. On a fresh
    # database (e.g. the pytest-django test DB) that signal has not fired yet
    # when this RunPython step executes, so the Permission table would still
    # be empty for models introduced earlier in this same migrate run. Force
    # permission creation now, against the historical (frozen) app registry,
    # so the filters below actually find rows.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, verbosity=0, apps=apps)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        if codenames == "__all__":
            permissions = Permission.objects.filter(
                content_type__app_label__in=APP_LABELS + ("auth",)
            )
        else:
            permissions = Permission.objects.filter(
                codename__in=codenames, content_type__app_label__in=APP_LABELS
            )
        group.permissions.set(permissions)


def delete_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUP_PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("people", "0002_household_householdmember"),
        ("committees", "0004_committeemembership_historicalcommitteemembership"),
        ("records", "0002_alter_accesslog_person"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_groups, delete_groups)]
