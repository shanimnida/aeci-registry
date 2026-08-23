from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import TimeStampedModel


class Committee(TimeStampedModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_self_selectable = models.BooleanField(
        default=True,
        help_text="Whether members may choose this committee on the profiling form.",
    )
    has_officers = models.BooleanField(
        default=True,
        help_text=(
            "Whether this committee has a chairperson, co-chair and secretary "
            "of its own. False for an appointed body whose members are named "
            "by the Board rather than led from within — Grievance and "
            "Reconciliation, whose members include the church's pastors. An "
            "empty officer post is not a vacancy for such a committee, so the "
            "overview stops reporting it as one."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class CommitteeFunction(models.Model):
    """A sub-team inside a committee, such as Transport within Sunshine."""

    committee = models.ForeignKey(
        Committee, on_delete=models.CASCADE, related_name="functions"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("committee__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["committee", "name"], name="unique_function_per_committee"
            )
        ]

    def __str__(self):
        return f"{self.committee.name} — {self.name}"


class Position(models.Model):
    """A church-level office, distinct from committee membership."""

    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    is_unique_holder = models.BooleanField(
        default=True, help_text="Whether only one person may hold this at a time."
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class AppointmentQuerySet(models.QuerySet):
    def active(self, on=None):
        on = on or timezone.localdate()
        return self.filter(start_date__lte=on).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=on)
        )


class Appointment(TimeStampedModel):
    """A church-level office held by a person -- Pastor, Treasurer,
    Secretary, Board Member. Distinct from a committee role, which is a
    CommitteeMembership; see spec 3.3. Shown as "Church positions" in the
    admin, because "Appointments" beside the committee-officer screen read
    as two ways to do the same thing."""


    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="appointments"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="appointments"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    history = HistoricalRecords()
    objects = AppointmentQuerySet.as_manager()

    class Meta:
        ordering = ("-start_date",)
        verbose_name = "church position"
        verbose_name_plural = "church positions"

    def __str__(self):
        return f"{self.person.full_name} — {self.position.name}"

    def clean(self):
        super().clean()
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date cannot precede the start date."})
        if not self.position_id or not self.position.is_unique_holder:
            return

        others = Appointment.objects.filter(position=self.position).exclude(pk=self.pk)
        for other in others:
            starts_before_other_ends = (
                other.end_date is None or self.start_date <= other.end_date
            )
            other_starts_before_this_ends = (
                self.end_date is None or other.start_date <= self.end_date
            )
            if starts_before_other_ends and other_starts_before_this_ends:
                raise ValidationError(
                    f"{other.person.full_name} already holds {self.position.name} "
                    f"over these dates. End that appointment first."
                )


BOARD_POSITION_CODES = ("board-member", "board-chairperson", "pastor")


class CommitteeRole(models.TextChoices):
    CHAIRPERSON = "CHAIRPERSON", "Chairperson"
    CO_CHAIR = "CO_CHAIR", "Co-Chair"
    # Added 2026-08-23 at the church's request: every committee keeps its own
    # secretary. An office, like Chairperson -- one at a time, hard refused.
    SECRETARY = "SECRETARY", "Secretary"
    MEMBER = "MEMBER", "Member"
    OVERSIGHT = "OVERSIGHT", "Board Oversight"
    # Added alongside SECRETARY, and not decoration. A committee secretary
    # sits on the Secretariat committee by virtue of their office, not
    # because they volunteered for it -- and Secretariat is self-selectable,
    # so recording that seat as MEMBER would count it against the profiling
    # form's "select up to TWO (2)" and warn about anyone holding a
    # secretary post plus two ticked committees, every time. EX_OFFICIO says
    # what the seat actually is. Unlike Chairperson and Secretary it is not
    # an office and carries no uniqueness rule: twelve secretaries all sit
    # on one Secretariat.
    EX_OFFICIO = "EX_OFFICIO", "Member by office"


class CommitteeMembershipQuerySet(models.QuerySet):
    def active(self, on=None):
        on = on or timezone.localdate()
        return self.filter(date_joined__lte=on).filter(
            Q(date_left__isnull=True) | Q(date_left__gte=on)
        )


class CommitteeMembership(TimeStampedModel):
    # Spec section 3.3: the profiling form prints "select up to TWO (2)
    # committees you wish to be part of." That is church policy printed on
    # a form, not a structural fact about the data -- see
    # self_selected_overflow_count() below for why it is no longer a hard
    # cap.
    SELF_SELECTED_LIMIT = 2

    # Appointed roles do not consume a self-selected slot. The form's
    # "select up to TWO (2)" asks what a member volunteers for; it says
    # nothing about what the Board or a committee appoints them to.
    APPOINTED_ROLES = (
        CommitteeRole.CHAIRPERSON,
        CommitteeRole.CO_CHAIR,
        CommitteeRole.SECRETARY,
        CommitteeRole.OVERSIGHT,
        CommitteeRole.EX_OFFICIO,
    )

    # Offices only one person may hold on a committee at a time. Both are
    # hard refusals: two people simultaneously chairing -- or keeping the
    # minutes of -- the same committee is structurally incoherent, not
    # merely against policy the way the two-committee cap was (R32).
    SOLE_OFFICE_ROLES = (CommitteeRole.CHAIRPERSON, CommitteeRole.SECRETARY)

    committee = models.ForeignKey(
        Committee, on_delete=models.PROTECT, related_name="memberships"
    )
    person = models.ForeignKey(
        "people.Person", on_delete=models.CASCADE, related_name="committee_memberships"
    )
    function = models.ForeignKey(
        CommitteeFunction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=12, choices=CommitteeRole.choices, default=CommitteeRole.MEMBER
    )
    date_joined = models.DateField()
    date_left = models.DateField(null=True, blank=True)

    history = HistoricalRecords()
    objects = CommitteeMembershipQuerySet.as_manager()

    class Meta:
        ordering = ("committee__name", "person__last_name")

    def __str__(self):
        return f"{self.person.full_name} — {self.committee.name} ({self.get_role_display()})"

    @property
    def is_active(self) -> bool:
        today = timezone.localdate()
        return self.date_joined <= today and (
            self.date_left is None or self.date_left >= today
        )

    def clean(self):
        super().clean()
        self._check_dates_are_ordered()
        self._check_function_belongs_to_committee()
        self._check_single_chairperson()
        self._check_one_role_per_committee()
        self._check_oversight_is_on_the_board()
        # The self-selected committee cap used to be checked here too, as a
        # hard refusal (self._check_self_selected_limit(), removed
        # 2026-08-17). It no longer blocks the save -- see
        # self_selected_overflow_count()'s docstring for why. Callers that
        # want to warn about it (committees/admin.py, imports/services.py)
        # call that method directly instead.

    # The Board's rule, recorded 2026-08-23: the Board appoints each
    # committee's chairperson, each chairperson appoints their own vice and
    # secretary, and every committee secretary is a member of the
    # Secretariat committee. That last clause is automatic -- not a
    # discretion the church exercises person by person -- so AEGIS keeps the
    # seat in step rather than prompting for it.
    SECRETARIAT_COMMITTEE_CODE = "secretariat"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._sync_secretariat_seat()

    def _sync_secretariat_seat(self):
        """Keep the Secretariat seat that follows from a secretary post in
        step with the post itself.

        Both directions, because half a rule is worse than none: taking a
        secretary post seats them on the Secretariat committee, and ending
        it un-seats them -- but only once they hold no OTHER active
        secretary post, since one person may keep the minutes for two
        committees and still be on Secretariat for the second.

        Only ever touches EX_OFFICIO rows. A Secretariat membership someone
        volunteered for is theirs, `role=MEMBER`, and is never ended here --
        losing a secretary post must not quietly cancel a committee they
        chose to serve on.
        """
        if self.role != CommitteeRole.SECRETARY:
            return
        if self.committee.code == self.SECRETARIAT_COMMITTEE_CODE:
            return
        secretariat = Committee.objects.filter(
            code=self.SECRETARIAT_COMMITTEE_CODE
        ).first()
        if secretariat is None:
            return

        still_a_secretary = (
            CommitteeMembership.objects.active()
            .filter(person=self.person, role=CommitteeRole.SECRETARY)
            .exclude(committee=secretariat)
            .exists()
        )
        seat = (
            CommitteeMembership.objects.active()
            .filter(
                person=self.person,
                committee=secretariat,
                role=CommitteeRole.EX_OFFICIO,
            )
            .first()
        )
        # Somebody who volunteered for Secretariat is already on it, and one
        # person holds one role on a committee at a time (see
        # _check_one_role_per_committee). Adding an ex-officio seat beside
        # their own membership would put them on the same roster twice.
        already_on_secretariat = (
            CommitteeMembership.objects.active()
            .filter(person=self.person, committee=secretariat)
            .exists()
        )

        if still_a_secretary and seat is None and not already_on_secretariat:
            seat = CommitteeMembership(
                committee=secretariat,
                person=self.person,
                role=CommitteeRole.EX_OFFICIO,
                date_joined=self.date_joined,
                created_by=self.created_by,
                updated_by=self.updated_by,
            )
            seat.full_clean()
            seat.save()
        elif not still_a_secretary and seat is not None:
            # Ends the day the last secretary post ended, not today, so the
            # service record reads truthfully.
            seat.date_left = self.date_left or timezone.localdate()
            seat.updated_by = self.updated_by
            seat.full_clean()
            seat.save()

    def _check_dates_are_ordered(self):
        """Mirrors Appointment.clean(): a transposed date must be rejected here too.

        Without this, a `date_joined` typed after `date_left` (a simple
        transposition, or a slip on a date picker) creates a row that
        active() excludes -- whichever date is wrong pushes it outside the
        active window -- and that _has_ended() treats as already finished.
        It would then count toward neither the two-committee cap nor the
        one-chairperson rule, and appear on no active roster: invisible,
        and exempt from every rule this model enforces, with nothing
        telling the person who typed it.

        A same-day join and leave is deliberately NOT rejected here:
        date_joined == date_left is not reversed, and active() already
        treats a membership ending today as still active today (see
        test_leaving_a_committee_frees_a_slot's semantics), so a
        zero-duration membership is a coherent, permitted case -- not the
        typo this check exists to catch.
        """
        if self.date_left and self.date_left < self.date_joined:
            raise ValidationError(
                {"date_left": "The end date cannot precede the start date."}
            )

    def _has_ended(self) -> bool:
        """True only once the membership is genuinely over.

        active() counts a membership ending today as still active, so a guard
        keyed on `self.date_left` being merely non-null would let a future
        departure date skip the check while the row is still live.
        """
        return self.date_left is not None and self.date_left < timezone.localdate()

    def _check_function_belongs_to_committee(self):
        if self.function_id and self.function.committee_id != self.committee_id:
            raise ValidationError(
                {"function": f"{self.function.name} is not part of {self.committee.name}."}
            )

    def self_selected_overflow_count(self) -> int | None:
        """The person's total active, self-selected, `role=MEMBER` committee
        count -- including this membership -- if it exceeds
        SELF_SELECTED_LIMIT; else None.

        Until 2026-08-17 this logic lived in `_check_self_selected_limit`,
        called from `clean()`, and it *raised* -- a third self-selected
        committee could not be saved at all. It no longer does: of the
        first thirty profiling forms collected, four (IMG_5874, IMG_5885,
        IMG_5893, IMG_5894) ticked three or four committees, and the church
        accepted those forms as filed. "Select up to TWO (2)" is a policy
        printed on the paper form, not a structural fact about the data the
        way "a committee cannot have two chairpersons at once" is --
        software refusing to save what the church itself already accepted
        was the software being wrong, not the form.

        So this only ever informs now. Callers (committees/admin.py's
        save_model, imports/services.py's committee_cap_warning) use the
        return value to tell a reviewer "N committees; the form asks for
        two," the same way people.admin.find_possible_duplicates warns
        about a possible duplicate person without blocking the save. Never
        raises.
        """
        if self.role in self.APPOINTED_ROLES or self._has_ended():
            return None
        if not self.committee.is_self_selectable:
            return None
        count = (
            CommitteeMembership.objects.active()
            .filter(person=self.person, role=CommitteeRole.MEMBER)
            .filter(committee__is_self_selectable=True)
            .exclude(pk=self.pk)
            .count()
        ) + 1
        if count > self.SELF_SELECTED_LIMIT:
            return count
        return None

    def _check_single_chairperson(self):
        """One holder at a time for each of SOLE_OFFICE_ROLES.

        Named for the chairperson rule it started as (spec 3.3 rule 2);
        it now covers Secretary on the same reasoning, which is why the
        message names whichever office is clashing rather than hardcoding
        one.
        """
        # A term whose end date has already arrived does not block its own
        # successor: handing over is something that happens on a single day,
        # and active() deliberately counts a membership ending today as
        # still active for roster purposes (R2). A FUTURE end date still
        # blocks, which is the bypass R12 closed.
        if self.role not in self.SOLE_OFFICE_ROLES or self._has_ended():
            return
        clash = (
            CommitteeMembership.objects.active()
            .filter(committee=self.committee, role=self.role)
            .exclude(pk=self.pk)
            .exclude(date_left__lte=timezone.localdate())
            .first()
        )
        if clash:
            raise ValidationError(
                f"{clash.person.full_name} is already "
                f"{self.get_role_display()} of {self.committee.name}. "
                "End that role first."
            )

    def _check_one_role_per_committee(self):
        """One person holds one role on a committee at a time.

        Added 2026-08-24 after the church found somebody down as both
        Chairperson and Member of the same committee: "a chairperson
        shouldnt even be marked as member since thats common sense." It is,
        and it is the same kind of rule as the one-chairperson rule -- a
        structural fact about what a roster means, not a policy the church
        might waive. Chairing a committee is a way of being on it, not a
        second thing you do there.

        Scoped to ACTIVE memberships, not enforced as a database
        constraint, because serving, leaving and later rejoining is
        ordinary and the history of it has to stay recordable.
        """
        if self._has_ended():
            return
        clash = (
            CommitteeMembership.objects.active()
            .filter(committee=self.committee, person=self.person)
            .exclude(pk=self.pk)
            .exclude(date_left__lte=timezone.localdate())
            .first()
        )
        if clash:
            raise ValidationError(
                f"{self.person.full_name} is already "
                f"{clash.get_role_display()} of {self.committee.name}. One "
                "person holds one role on a committee at a time — change the "
                "existing role rather than adding a second."
            )

    def _check_oversight_is_on_the_board(self):
        if self.role != CommitteeRole.OVERSIGHT:
            return
        on_board = (
            Appointment.objects.active()
            .filter(person=self.person, position__code__in=BOARD_POSITION_CODES)
            .exists()
        )
        if not on_board:
            raise ValidationError(
                f"{self.person.full_name} holds no active Board appointment, so they "
                f"cannot be Board Oversight. Record the appointment first."
            )
