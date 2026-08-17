import csv
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from committees.models import Committee, CommitteeMembership, CommitteeRole
from people.models import Person

REQUIRED_COLUMNS = {
    "last_name",
    "first_name",
    "nickname",
    "membership_status",
    "committee_code",
    "role",
    "start_date",
}

# Holding two of these at once is the anomaly worth stopping a human to
# look at -- a spreadsheet's committee_code cell most likely got edited to
# move someone. MEMBER and OVERSIGHT are deliberately excluded: a second
# (or third, or fourth) active MEMBER role on a different self-selectable
# committee is legal -- CommitteeMembership no longer refuses any number of
# these, only warns above the profiling form's printed cap of two (see
# CommitteeMembership.self_selected_overflow_count) -- and OVERSIGHT has its
# own active-Board-appointment rule. The model is the authority on what's
# valid; this command only catches the one case the model's per-committee
# rules can't see on their own.
ROLES_LIMITED_TO_ONE_COMMITTEE = {CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR}


class Command(BaseCommand):
    help = (
        "Create officer Person records and their committee roles from a CSV "
        "(data/officers.csv by default). Idempotent -- safe to run repeatedly "
        "as names get resolved. NOTE: officers known to the Board only by "
        "first name or nickname (e.g. MJ, Jemuel, JM, Fredalyn, Diego, "
        "Juliet) are deliberately absent from the CSV pending manual name "
        "resolution by the ICT Committee -- this command never guesses a "
        "surname to fill a row. membership_status is likewise a required "
        "column the ICT Committee states, never a default this command "
        "picks -- a new officer is created at whatever status the CSV "
        "names, and an officer who already exists on file keeps their "
        "recorded status untouched no matter what the CSV says. Every "
        "Person and CommitteeMembership is validated with full_clean() "
        "before it is saved, so a row that would break a business rule (a "
        "second Chairperson for a committee, Board Oversight for someone "
        "with no active Board appointment, and so on) is reported by row "
        "number and skipped rather than silently applied or half-saved; "
        "the command exits "
        "non-zero if any row failed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="data/officers.csv",
            help="Path to the officers CSV (default: data/officers.csv).",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(
                f"{path} not found. Create it with columns: "
                f"{','.join(sorted(REQUIRED_COLUMNS))}"
            )

        # utf-8-sig strips a leading byte-order mark when present (Excel's
        # "CSV UTF-8" export writes one, which would otherwise turn
        # "last_name" into "﻿last_name" and make a present column look
        # missing) and is harmless when there is no BOM at all.
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing_columns:
                raise CommandError(
                    f"{path} is missing column(s): {', '.join(sorted(missing_columns))}. "
                    f"Expected header: last_name,first_name,nickname,membership_status,"
                    f"committee_code,role,start_date"
                )
            rows = list(reader)

        created_people = created_roles = 0
        row_errors = []
        nickname_updates = []

        # Row 1 is the header, so the first data row is line 2 -- matching
        # what the ICT Committee sees if they open the CSV in a spreadsheet.
        for line_no, row in enumerate(rows, start=2):
            try:
                with transaction.atomic():
                    person_created, role_created, nickname_update = self._seed_row(row)
            except ValidationError as exc:
                row_errors.append(self._describe_error(line_no, row, exc))
                continue
            created_people += int(person_created)
            created_roles += int(role_created)
            if nickname_update:
                nickname_updates.append(nickname_update)

        for update in nickname_updates:
            self.stdout.write(update)

        for error in row_errors:
            self.stderr.write(self.style.ERROR(error))

        self.stdout.write(
            f"Created {created_people} person(s) and {created_roles} "
            f"committee role(s) from {len(rows)} row(s)."
        )

        if row_errors:
            raise CommandError(
                f"{len(row_errors)} of {len(rows)} row(s) failed validation and were "
                f"skipped -- see the errors above. Fix the CSV and re-run; rows that "
                f"already succeeded will not be duplicated."
            )

        self.stdout.write(self.style.SUCCESS("All rows imported cleanly."))

    def _seed_row(self, row):
        """Create (or find) the Person and CommitteeMembership for one CSV row.

        Every write is preceded by full_clean() per CONTROLLER RULING R10:
        Model.save() does not enforce the business rules in Model.clean(),
        and this command is the one non-admin write path in the system, so
        it has to do explicitly what the admin's ModelForm does for free.
        """
        last_name = (row.get("last_name") or "").strip()
        first_name = (row.get("first_name") or "").strip()
        nickname = (row.get("nickname") or "").strip()
        membership_status = (row.get("membership_status") or "").strip()
        committee_code = (row.get("committee_code") or "").strip()
        role = (row.get("role") or "").strip()
        start_date = (row.get("start_date") or "").strip()

        try:
            committee = Committee.objects.get(code=committee_code)
        except Committee.DoesNotExist:
            raise ValidationError(
                f"No committee with code {committee_code!r}. Check the spelling "
                f"against committees/migrations/0002_seed_committees.py."
            )

        person = Person.objects.filter(
            last_name=last_name, first_name=first_name
        ).first()
        person_created = False
        nickname_update = None
        if person is None:
            # membership_status comes from the CSV, not a default this
            # command picks -- the ICT Committee states the fact (their
            # source is the Board minutes that name these people as
            # chairpersons), the code only records it. A blank value is
            # rejected by Person.full_clean() below rather than silently
            # falling back to the model's own RELATED default: RELATED
            # would misdescribe an actual chairperson, and any default this
            # command chose on its own would be the software deciding
            # membership, which is exactly what it must never do.
            #
            # Setting membership_status directly on a *new* instance does
            # not require approved_by even when the value is MEMBER: Person
            # only demands one when an EXISTING record (loaded from the
            # database, so _loaded_status is set) changes to MEMBER. A
            # brand-new row has no _loaded_status, so this is "creating a
            # record already at MEMBER" -- the documented, deliberate path
            # for encoding a backlog whose approving meeting predates this
            # system. See people/models.py Person.clean().
            #
            # This only ever applies to a person being created for the
            # first time. An existing person's membership_status is never
            # touched here (only their nickname, below, and only when the
            # CSV supplies a new one) -- a re-run must not promote anyone
            # who is already on file, silently or otherwise.
            person = Person(
                last_name=last_name,
                first_name=first_name,
                nickname=nickname,
                membership_status=membership_status,
            )
            person.full_clean()
            person.save()
            person_created = True
        elif nickname and person.nickname != nickname:
            # The CSV exists precisely so nicknames get resolved to full
            # names over time -- apply a corrected value on a re-run
            # instead of silently ignoring it. A blank CSV nickname is not
            # an instruction to erase a stored one, so this only fires
            # when the row actually supplies a different, non-empty value.
            old_nickname = person.nickname
            person.nickname = nickname
            person.full_clean()
            person.save(update_fields=["nickname"])
            nickname_update = (
                f"{person.full_name}: nickname changed from "
                f"{old_nickname!r} to {nickname!r}."
            )

        role_created = False
        existing_membership = CommitteeMembership.objects.filter(
            person=person, committee=committee, role=role
        ).exists()
        if not existing_membership and role in ROLES_LIMITED_TO_ONE_COMMITTEE:
            # A person already active in this same role on a *different*
            # committee is most likely a CSV row that got its
            # committee_code edited to move them -- not an instruction to
            # give them a second simultaneous role. Editing a spreadsheet
            # is not a reliable signal to end their existing membership,
            # so refuse rather than silently create a duplicate; the
            # operator ends the old one in the admin and re-runs. Scoped
            # to CHAIRPERSON/CO_CHAIR only -- see ROLES_LIMITED_TO_ONE_COMMITTEE.
            conflict = (
                CommitteeMembership.objects.active()
                .filter(person=person, role=role)
                .exclude(committee=committee)
                .first()
            )
            if conflict:
                role_label = dict(CommitteeRole.choices).get(role, role)
                raise ValidationError(
                    f"{person.full_name} already holds an active "
                    f"{role_label} membership on {conflict.committee.name}. "
                    f"This row would give them a second {role_label} at "
                    f"the same time (on {committee.name}). End the "
                    f"{conflict.committee.name} membership in the admin "
                    f"first, then re-run."
                )
        if not existing_membership:
            membership = CommitteeMembership(
                person=person,
                committee=committee,
                role=role,
                date_joined=start_date,
            )
            membership.full_clean()
            membership.save()
            role_created = True

        return person_created, role_created, nickname_update

    def _describe_error(self, line_no, row, exc):
        who = " ".join(
            part
            for part in (row.get("last_name", "").strip(), row.get("first_name", "").strip())
            if part
        ) or "(name missing)"
        return f"Row {line_no} ({who}): {self._format_validation_error(exc)}"

    def _format_validation_error(self, exc):
        if hasattr(exc, "message_dict"):
            parts = []
            for field, messages in exc.message_dict.items():
                prefix = "" if field == "__all__" else f"{field}: "
                parts.append(prefix + " ".join(messages))
            return "; ".join(parts)
        return "; ".join(exc.messages)
