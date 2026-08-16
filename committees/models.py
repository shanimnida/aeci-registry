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
    MEMBER = "MEMBER", "Member"
    OVERSIGHT = "OVERSIGHT", "Board Oversight"


class CommitteeMembershipQuerySet(models.QuerySet):
    def active(self, on=None):
        on = on or timezone.localdate()
        return self.filter(date_joined__lte=on).filter(
            Q(date_left__isnull=True) | Q(date_left__gte=on)
        )


class CommitteeMembership(TimeStampedModel):
    # Spec section 3.3: the profiling form says "select up to TWO (2)".
    SELF_SELECTED_LIMIT = 2

    # Appointed roles do not consume a self-selected slot.
    APPOINTED_ROLES = (
        CommitteeRole.CHAIRPERSON,
        CommitteeRole.CO_CHAIR,
        CommitteeRole.OVERSIGHT,
    )

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
        self._check_function_belongs_to_committee()
        self._check_self_selected_limit()
        self._check_single_chairperson()
        self._check_oversight_is_on_the_board()

    def _check_function_belongs_to_committee(self):
        if self.function_id and self.function.committee_id != self.committee_id:
            raise ValidationError(
                {"function": f"{self.function.name} is not part of {self.committee.name}."}
            )

    def _check_self_selected_limit(self):
        if self.role in self.APPOINTED_ROLES or self.date_left:
            return
        if not self.committee.is_self_selectable:
            return
        existing = (
            CommitteeMembership.objects.active()
            .filter(person=self.person, role=CommitteeRole.MEMBER)
            .filter(committee__is_self_selectable=True)
            .exclude(pk=self.pk)
            .count()
        )
        if existing >= self.SELF_SELECTED_LIMIT:
            raise ValidationError(
                f"{self.person.full_name} already serves on "
                f"{self.SELF_SELECTED_LIMIT} committees. A member may choose up to two. "
                f"End an existing membership first."
            )

    def _check_single_chairperson(self):
        if self.role != CommitteeRole.CHAIRPERSON or self.date_left:
            return
        clash = (
            CommitteeMembership.objects.active()
            .filter(committee=self.committee, role=CommitteeRole.CHAIRPERSON)
            .exclude(pk=self.pk)
            .first()
        )
        if clash:
            raise ValidationError(
                f"{clash.person.full_name} is already Chairperson of "
                f"{self.committee.name}. End that role first."
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
