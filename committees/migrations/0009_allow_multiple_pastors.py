from django.db import migrations


def allow_multiple_pastors(apps, schema_editor):
    apps.get_model("committees", "Position").objects.using(
        schema_editor.connection.alias
    ).filter(code="pastor").update(is_unique_holder=False)


class Migration(migrations.Migration):
    dependencies = [("committees", "0008_grievance_has_no_officers")]
    # Do not reintroduce a single-holder rule on rollback after several
    # pastors have been recorded.
    operations = [migrations.RunPython(allow_multiple_pastors, migrations.RunPython.noop)]
