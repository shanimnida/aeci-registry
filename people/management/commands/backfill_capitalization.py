from django.core.management.base import BaseCommand

from core.capitalization import capitalize_suffix, capitalize_words
from people.models import Household, Person


class Command(BaseCommand):
    help = (
        "Re-normalize capitalization on every existing Person and Household "
        "row. core.capitalization already runs on save() for both models "
        "(Person.save(), Household.save()), but that only ever touches a "
        "row the moment it is written -- it does nothing for a row that "
        "already existed on disk before the rule applied to its field (e.g. "
        "Household.address, only just added to Household.CAPITALIZED_FIELDS) "
        "or that was written by some path that bypassed save(). This "
        "command closes that gap once, for the whole table.\n\n"
        "Writes with a queryset update(), not Person.save()/Household.save(), "
        "deliberately. Person carries django-simple-history: calling save() "
        "on every row would write a full historical revision per person -- "
        "dozens of fabricated 'edits', all stamped at backfill time with no "
        "real author, in an audit trail that exists precisely so a member "
        "can be told who changed their record and when. A one-off cosmetic "
        "re-casing is not that kind of edit, and does not deserve to look "
        "like one forever after. The trade-off is real: update() also skips "
        "the rest of what Person.save() does -- maintaining has_missing_data "
        "and status_changed_at. Neither can actually fire here, though: "
        "capitalize_words()/capitalize_suffix() only ever change a field's "
        "*case*, never whether it is blank, so has_missing_data cannot "
        "change; and this command never touches membership_status, so "
        "status_changed_at cannot either. Nothing about this change is "
        "audit-worthy, so it is written unaudited."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        people_changed = self._backfill(Person, dry_run, label=lambda p: p.full_name)
        households_changed = self._backfill(Household, dry_run, label=lambda h: h.name)

        verb = "Would capitalize" if dry_run else "Capitalized"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {people_changed} person(s) and {households_changed} "
                f"household(s)."
            )
        )
        return f"{people_changed},{households_changed}"

    def _backfill(self, model, dry_run, label) -> int:
        """Recompute model.CAPITALIZED_FIELDS for every row of `model`.

        `suffix` is Person-only and is not in CAPITALIZED_FIELDS (see
        Person.save() -- it needs capitalize_suffix, not capitalize_words,
        so III does not turn into Iii). Handled as one extra field here
        rather than a second pass, so it participates in the same
        per-row "did anything actually change" count and dry-run report.
        """
        changed = 0
        for obj in model.objects.all():
            updates = {}
            for field_name in model.CAPITALIZED_FIELDS:
                current = getattr(obj, field_name)
                normalized = capitalize_words(current)
                if normalized != current:
                    updates[field_name] = normalized
            if model is Person:
                normalized_suffix = capitalize_suffix(obj.suffix)
                if normalized_suffix != obj.suffix:
                    updates["suffix"] = normalized_suffix

            if not updates:
                continue
            changed += 1
            if dry_run:
                self.stdout.write(
                    f"{label(obj)}: would capitalize {', '.join(sorted(updates))}"
                )
                continue
            model.objects.filter(pk=obj.pk).update(**updates)
        return changed
