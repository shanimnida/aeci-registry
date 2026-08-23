from django.db import migrations

GRIEVANCE_CODE = "grievance-and-reconciliation"


def mark_grievance(apps, schema_editor):
    """Grievance and Reconciliation has no chairperson, co-chair or secretary.

    Recorded 2026-08-24 from the church: "the Grievance and Reconciliation
    Committee doesnt need a Chair and Co-Chair, the members are appointed as
    well such as the two Pastors of the Church". It is an appointed body --
    the Board names who sits on it, and it is not led from within the way the
    eleven self-selectable committees are. D7 already made it the one
    committee absent from the profiling form; this is the other half of the
    same fact.

    The consequence is only in reporting: an empty chairperson post is not a
    VACANCY here, so the committee overview stops listing it as one. Nothing
    prevents an officer being recorded if the Board ever appoints one.
    """
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(code=GRIEVANCE_CODE).update(has_officers=False)


def unmark_grievance(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(code=GRIEVANCE_CODE).update(has_officers=True)


class Migration(migrations.Migration):
    dependencies = [("committees", "0007_committee_has_officers")]
    operations = [migrations.RunPython(mark_grievance, unmark_grievance)]
