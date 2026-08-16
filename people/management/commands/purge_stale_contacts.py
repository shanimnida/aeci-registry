import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from people.models import MembershipStatus, Person

PURGEABLE_STATUSES = (MembershipStatus.TRANSFERRED, MembershipStatus.DECEASED)


class Command(BaseCommand):
    help = (
        "Clear contact details for people who transferred or died more than "
        "CONTACT_RETENTION_DAYS ago. Identity and membership history are kept "
        "permanently; rows are never deleted. Spec section 5.1."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be cleared without changing anything.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - dt.timedelta(days=settings.CONTACT_RETENTION_DAYS)
        stale = Person.objects.filter(
            membership_status__in=PURGEABLE_STATUSES, status_changed_at__lt=cutoff
        )

        purged = 0
        for person in stale:
            fields = [f for f in Person.CONTACT_FIELDS if getattr(person, f)]
            if not fields:
                continue
            purged += 1
            self.stdout.write(
                f"{person.full_name}: clearing {', '.join(fields)}"
            )
            if options["dry_run"]:
                continue
            for field in fields:
                setattr(person, field, "")
            person.save(update_fields=fields)

        verb = "Would clear" if options["dry_run"] else "Cleared"
        self.stdout.write(self.style.SUCCESS(f"{verb} contact details for {purged} person(s)."))
        return str(purged)
