from django.db import migrations

POSITIONS = [
    ("Pastor", "pastor", True),
    ("Chairperson of the Board", "board-chairperson", True),
    ("Treasurer", "treasurer", True),
    ("Secretary", "secretary", True),
    ("Board Member", "board-member", False),
]


def seed(apps, schema_editor):
    Position = apps.get_model("committees", "Position")
    for name, code, unique in POSITIONS:
        Position.objects.get_or_create(
            code=code, defaults={"name": name, "is_unique_holder": unique}
        )


def unseed(apps, schema_editor):
    Position = apps.get_model("committees", "Position")
    Position.objects.filter(code__in=[code for _, code, _ in POSITIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0003_position_historicalappointment_appointment")]
    operations = [migrations.RunPython(seed, unseed)]
