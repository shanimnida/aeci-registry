import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from people.models import Household, HouseholdRole


class Command(BaseCommand):
    help = (
        "Remove households that hold nothing worth keeping. "
        "imports/services.py used to create a Household for every approved "
        "import row unconditionally -- even a single member with no spouse, "
        "no children and no date of marriage, which is not a family at all "
        "(see build_person_from_import's 2026-08-22 fix). Importing thirty "
        "solo forms manufactured thirty such households. This command "
        "cleans up the ones that bug already wrote to the database.\n\n"
        "A household only qualifies if it has exactly one member, that "
        "member's role is HEAD, and the household carries no "
        "date_of_marriage -- any household with more than one member, any "
        "member whose role is not HEAD, or a recorded marriage date is left "
        "untouched, because any of those means there is a family here, "
        "however thin the record. Before deleting, the lone member's own "
        "home_address is backfilled from the household's address if it is "
        "still blank, so the address is not lost.\n\n"
        "IMPORTANT -- read before running this a second time. Those criteria "
        "do NOT single out the bug's output. The fixed importer still "
        "creates a one-HEAD household with no marriage date in one case: a "
        "form that names a spouse who is not in the register yet. Nothing "
        "on the household distinguishes that from a household the bug "
        "made, so a later re-run would delete it too. Use --created-before "
        "with the date this fix was deployed to scope a run to households "
        "that predate it; the dry-run listing prints each household's "
        "creation date so you can see which are which.\n\n"
        "HouseholdMember.household is CASCADE and HouseholdMember carries "
        "no history (unlike Person), so a deletion here is genuinely "
        "unrecoverable -- always run with --dry-run first."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without changing anything.",
        )
        parser.add_argument(
            "--created-before",
            metavar="YYYY-MM-DD",
            help=(
                "Only consider households created before this date. Use the date the "
                "empty-households fix was deployed, so a re-run cannot delete the "
                "one-HEAD households the fixed importer legitimately creates for a form "
                "naming a spouse who is not in the register yet. The boundary is local "
                "midnight, so households created on the date itself are spared -- if the "
                "last buggy import ran on deployment day, pass the day after."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = self._parse_cutoff(options.get("created_before"))
        removed = 0

        # date_of_marriage is a household-level fact with no home on Person
        # (see imports/services.py's module docstring) -- a household that
        # carries one is never a candidate, no matter its membership.
        candidates = Household.objects.filter(date_of_marriage__isnull=True).prefetch_related(
            "members__person"
        )
        if cutoff is not None:
            candidates = candidates.filter(created_at__lt=cutoff)
        for household in candidates:
            members = list(household.members.all())
            if len(members) != 1:
                continue
            (member,) = members
            if member.role != HouseholdRole.HEAD:
                continue

            person = member.person
            created = timezone.localtime(household.created_at).date()
            label = (
                f"{household} (#{household.pk}, created {created}, "
                f"sole member {person.full_name})"
            )

            if dry_run:
                self.stdout.write(f"{label}: would remove")
                removed += 1
                continue

            with transaction.atomic():
                if not person.home_address and household.address:
                    # Move the address out before the household holding it
                    # disappears -- see the command's own help text on why
                    # this delete cannot be undone.
                    person.home_address = household.address
                    person.full_clean()
                    person.save()
                household.delete()

            self.stdout.write(f"{label}: removed")
            removed += 1

        verb = "Would remove" if dry_run else "Removed"
        self.stdout.write(self.style.SUCCESS(f"{verb} {removed} empty household(s)."))
        return str(removed)

    def _parse_cutoff(self, raw):
        """Turn --created-before into an aware datetime at local midnight.

        Compared against created_at (a DateTimeField) rather than using a
        __date lookup so the boundary is unambiguous under TIME_ZONE:
        "before 2026-08-23" means before midnight Manila time on that day,
        which is what someone reading the deployment date means by it.
        """
        if not raw:
            return None
        try:
            day = dt.date.fromisoformat(raw)
        except ValueError:
            raise CommandError(f"--created-before must be YYYY-MM-DD, not {raw!r}.")
        return timezone.make_aware(dt.datetime.combine(day, dt.time.min))
