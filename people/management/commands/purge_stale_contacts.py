import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from people.models import Household, MembershipStatus, Person
from records.models import FormScan, PurgeRecord

PURGEABLE_STATUSES = (MembershipStatus.TRANSFERRED, MembershipStatus.DECEASED)


class Command(BaseCommand):
    help = (
        "Clear contact details -- on the live row, in history, on a "
        "vacated household address, and on any linked form-scan images -- "
        "for people who transferred or died more than CONTACT_RETENTION_DAYS "
        "ago. Identity and membership history are kept permanently; rows are "
        "never deleted. Writes one PurgeRecord per person purged. Spec "
        "section 5.1."
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
            dirty_scans = self._dirty_scans(person)

            if not live_fields and not dirty_history.exists() and not dirty_scans.exists():
                # Live row, every historical revision, and every scan image
                # are already blank/gone (e.g. a previous run already purged
                # this person). Nothing left to do, so don't count or log
                # them again.
                continue

            if dry_run:
                purged += 1
                self.stdout.write(f"{person.full_name}: would clear contact data")
                continue

            # Scrub history first: it holds values for fields the live row
            # may no longer have, so it must be cleared unconditionally on
            # every stale person, not just ones with live data left.
            history_rows_scrubbed = self._scrub_history(person)

            # The scanned paper form is a photograph of the same contact
            # data -- name, address, mobile number, emergency contact -- so
            # leaving the image in storage would defeat the policy just as
            # surely as leaving it on the live row or in history. The
            # FormScan row (form_type, uploaded_by, uploaded_at) stays: the
            # register must still show a form existed and was encoded.
            scan_files_removed = self._purge_scans(person)

            if live_fields:
                for field in live_fields:
                    setattr(person, field, "")
                person.save(update_fields=live_fields)

            purged += 1
            self.stdout.write(
                f"{person.full_name}: cleared "
                f"{', '.join(live_fields) or 'history only'} "
                f"({history_rows_scrubbed} history row(s), "
                f"{scan_files_removed} scan file(s))"
            )
            PurgeRecord.objects.create(
                person=person,
                person_label=f"{person.member_no or '-'} {person.full_name}",
                fields_cleared=", ".join(Person.CONTACT_FIELDS),
                history_rows_scrubbed=history_rows_scrubbed,
                scan_files_removed=scan_files_removed,
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

    def _dirty_scans(self, person):
        """This person's form scans that still have an image file (read-only)."""
        return FormScan.objects.filter(person=person).exclude(file="")

    def _purge_scans(self, person) -> int:
        """Delete the stored photograph for each of this person's form scans.

        The photograph encodes the same contact data the rest of this
        command clears -- handwritten name, birthdate, address, mobile
        number, emergency contact, spouse and children -- so leaving it in
        object storage would defeat the retention policy through an image
        file. Only the file is removed; the FormScan row survives with its
        form_type, uploaded_by and uploaded_at intact, so the register still
        shows a form existed and was encoded.

        Uses the storage API (not the filesystem directly) so this works
        against local FileSystemStorage in development and the S3-compatible
        backend in production. A scan whose file is already gone (a prior
        run, manual cleanup, a bucket lifecycle rule) must not abort the
        purge for the rest of this person or for anyone else.
        """
        removed = 0
        for scan in self._dirty_scans(person):
            try:
                scan.file.delete(save=False)
            except Exception as exc:  # noqa: BLE001 -- storage backends raise different types
                self.stderr.write(
                    f"{person.full_name}: could not delete scan file "
                    f"{scan.file.name!r} ({exc}); clearing the reference anyway"
                )
            scan.file = ""
            scan.save(update_fields=["file"])
            removed += 1
        return removed

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
