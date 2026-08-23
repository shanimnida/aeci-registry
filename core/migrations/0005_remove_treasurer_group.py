from django.db import migrations

GROUP_NAME = "Treasurer"


def remove_treasurer_group(apps, schema_editor):
    """Drop the Treasurer login group.

    It was created empty in 0002 so that Phase B and C accounts would slot
    in without a migration mid-flight, and so spec 4's separation-of-duties
    table had no gap in it. Removed 2026-08-24 on the church's decision: the
    Treasurer has not asked for anything, so the phase this was reserved
    for is not merely unbuilt but unconfirmed. A role holding no permissions
    is a checkbox on the account form that silently grants nothing, and a
    login that signs in to an empty admin reads as broken rather than as
    pending.

    Nothing functional changes. The group held zero permissions, so anybody
    in it loses nothing they had.

    NOTE this is the login GROUP only. The Treasurer POSITION -- the actual
    church office, seeded by committees.0003_seed_positions and held by a
    real person whose appointment is recorded -- is untouched. Phase C, if
    it ever happens, can create a group again; that is one migration, which
    is exactly the cost 0002 was trying to avoid and is not a large one.
    """
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


def restore_treasurer_group(apps, schema_editor):
    """Recreate it empty, which is the state it was always in."""
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GROUP_NAME)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_fix_group_permissions"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [
        migrations.RunPython(remove_treasurer_group, restore_treasurer_group)
    ]
