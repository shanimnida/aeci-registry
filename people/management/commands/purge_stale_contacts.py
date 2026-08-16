import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from people.models import Household, MembershipStatus, Person
from records.models import PurgeRecord

PURGEABLE_STATUSES = (MembershipStatus.TRANSFERRED, MembershipStatus.DECEASED)


class Command(BaseCommand):
    help = (
        "Clear contact details -- on the live row, in history, and on a "
        "vacated household address -- for people who transferred or died "
        "more than CONTACT_RETENTION_DAYS ago. Identity and membership "
        "history are kept permanently; rows are never deleted. Writes one "
        "PurgeRecord per person purged. Spec section 5.1."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be cleared without changing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - dt.timedelta(days=settings.CONTACT_RETENTION_DAYS)
        stale = Person.objects.filter(
            membership_status__in=PURGEABLE_STATUSES, status_changed_at__lt=cutoff
        )

        purged = 0
        for person in stale:
            live_fields = [f for f in Person.CONTACT_FIELDS if getattr(person, f)]
            dirty_history = self._dirty_history(person)

            if not live_fields and not dirty_history.exists():
                # Live row and every historical revision are already blank
                # (e.g. a previous run already purged this person). Nothing
                # left to do, so don't count or log them again.
                continue

            if dry_run:
                purged += 1
                self.stdout.write(f"{person.full_name}: would clear contact data")
                continue

            # Scrub history first: it holds values for fields the live row
            # may no longer have, so it must be cleared unconditionally on
            # every stale person, not just ones with live data left.
            history_rows_scrubbed = self._scrub_history(person)

            if live_fields:
                for field in live_fields:
                    setattr(person, field, "")
                person.save(update_fields=live_fields)

            purged += 1
            self.stdout.write(
                f"{person.full_name}: cleared "
                f"{', '.join(live_fields) or 'history only'} "
                f"({history_rows_scrubbed} history row(s))"
            )
            PurgeRecord.objects.create(
                person=person,
                person_label=f"{person.member_no or '-'} {person.full_name}",
                fields_cleared=", ".join(Person.CONTACT_FIELDS),
                history_rows_scrubbed=history_rows_scrubbed,
            )

        households_cleared = 0 if dry_run else self._purge_vacated_households(cutoff)

        verb = "Would clear" if dry_run else "Cleared"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} contact details for {purged} person(s); "
                f"cleared {households_cleared} household address(es)."
            )
        )
        return str(purged)

    def _dirty_history(self, person):
        """The historical revisions that still hold contact data (read-only)."""
        blanks = {field: "" for field in Person.CONTACT_FIELDS}
        return Person.history.filter(id=person.pk).exclude(**blanks)

    def _scrub_history(self, person) -> int:
        """Blank the same fields on every stored revision.

        Clearing only the live row leaves every prior value readable on the
        admin history page, so the retention policy would not be delivered.
        """
        blanks = {field: "" for field in Person.CONTACT_FIELDS}
        return Person.history.filter(id=person.pk).exclude(**blanks).update(**blanks)

    def _purge_vacated_households(self, cutoff):
        """Clear a household address only once nobody in it is still current."""
        cleared = 0
        for household in Household.objects.exclude(address=""):
            members = Person.objects.filter(household_memberships__household=household)
            if not members.exists():
                continue
            still_current = members.exclude(
                membership_status__in=PURGEABLE_STATUSES, status_changed_at__lt=cutoff
            ).exists()
            if still_current:
                continue
            household.address = ""
            household.save(update_fields=["address"])
            cleared += 1
        return cleared
