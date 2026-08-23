from django.core.management.base import BaseCommand
from django.db import transaction

from core.numbering import member_no_is_valid, new_member_no


class Command(BaseCommand):
    help = (
        "Replace old sequential member numbers with random ones.\n\n"
        "Member numbers used to be issued in order — MEM-0001, MEM-0002 — "
        "which told anyone holding one roughly how many members the church "
        "has and who joined before whom. That was fine on an internal form "
        "and stops being fine once the number is printed on a card a member "
        "carries. Numbers are now MEM- plus six random digits and a seventh "
        "check digit.\n\n"
        "This renumbers everyone still on the old shape. A number that "
        "already passes the check-digit test is left alone, which is what "
        "makes the command safe to run twice: after one clean run there is "
        "nothing left for it to change.\n\n"
        "That also means a number set BY HAND survives a re-run only if its "
        "check digit is right. Use --dry-run first; it prints every change "
        "it would make, old number to new."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        from people.models import Person

        dry_run = options["dry_run"]
        changed = 0

        # Only people who actually hold a number. Somebody with none is not
        # renumbered into having one -- issuing a number to a person the
        # church never accepted is exactly what D9 exists to prevent, and
        # "Assign member numbers" in the admin is the deliberate way to do
        # it.
        candidates = Person.objects.exclude(member_no__isnull=True).exclude(member_no="")
        for person in candidates.order_by("pk"):
            if member_no_is_valid(person.member_no):
                continue

            old = person.member_no
            if dry_run:
                # Not allocated, so it is not reserved and not shown -- a
                # dry run must not consume or promise a number.
                self.stdout.write(f"{person.full_name}: {old} -> (a new random number)")
                changed += 1
                continue

            with transaction.atomic():
                person.member_no = new_member_no()
                person.save(update_fields=["member_no"])
            self.stdout.write(f"{person.full_name}: {old} -> {person.member_no}")
            changed += 1

        verb = "Would renumber" if dry_run else "Renumbered"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changed} member(s)."))
