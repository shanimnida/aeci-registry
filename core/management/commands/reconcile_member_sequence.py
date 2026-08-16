from django.core.management.base import BaseCommand

from core.numbering import reconcile_member_sequence


class Command(BaseCommand):
    help = (
        "Advance the MEM- control number sequence to at least the highest "
        "member_no already on file. Run this after a batch of hand-encoded "
        "MEM- numbers (typed in straight from paper forms) so 'Assign "
        "member numbers' cannot hand out a number that collides with, or "
        "leaves a permanent gap around, one already written on paper. Safe "
        "to run any number of times; next_member_no() also calls this "
        "itself before every allocation, so running the command is a "
        "belt-and-braces check, not a requirement."
    )

    def handle(self, *args, **options):
        last_value = reconcile_member_sequence()
        self.stdout.write(
            self.style.SUCCESS(
                f"MEM sequence reconciled: last_value is now {last_value:04d}."
            )
        )
