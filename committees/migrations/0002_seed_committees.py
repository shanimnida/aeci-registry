from django.db import migrations

# Spec section 3.3. Twelve committees; Grievance and Reconciliation is
# appointed by the Board rather than chosen, so it is not self-selectable.
COMMITTEES = [
    ("Sunshine", "sunshine", True, ["Ushering and Marshall", "Transport", "Benevolence"]),
    ("General Services", "general-services", True,
     ["Construction and Repair", "Maintenance", "Building Tools"]),
    ("Property and Supplies", "property-and-supplies", True,
     ["Musical Instruments", "Supplies"]),
    ("Music and Arts", "music-and-arts", True, ["Sounds", "Song Leading", "Instrument"]),
    ("Children's Ministry", "childrens-ministry", True, []),
    ("Youth", "youth", True, []),
    ("Events", "events", True, []),
    ("Finance and Resource Accessing", "finance-and-resource-accessing", True, []),
    ("Grievance and Reconciliation", "grievance-and-reconciliation", False, []),
    ("ICT", "ict", True, []),
    ("Secretariat", "secretariat", True, []),
    ("Food", "food", True, []),
]


def seed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    CommitteeFunction = apps.get_model("committees", "CommitteeFunction")
    for name, code, selectable, functions in COMMITTEES:
        committee, _ = Committee.objects.get_or_create(
            code=code, defaults={"name": name, "is_self_selectable": selectable}
        )
        for function_name in functions:
            CommitteeFunction.objects.get_or_create(
                committee=committee, name=function_name
            )


def unseed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(code__in=[code for _, code, _, _ in COMMITTEES]).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
