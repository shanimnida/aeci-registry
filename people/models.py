from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import TimeStampedModel


class MembershipStatus(models.TextChoices):
    MEMBER = "MEMBER", "Member"
    CHILD = "CHILD", "Child"
    RELATED = "RELATED", "Related (spouse or guardian, not a member)"
    VISITOR = "VISITOR", "Visitor"
    INACTIVE = "INACTIVE", "Inactive"
    TRANSFERRED = "TRANSFERRED", "Transferred"
    DECEASED = "DECEASED", "Deceased"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"


class CivilStatus(models.TextChoices):
    SINGLE = "SINGLE", "Single"
    MARRIED = "MARRIED", "Married"
    WIDOWED = "WIDOWED", "Widowed"
    SEPARATED = "SEPARATED", "Separated"
    ANNULLED = "ANNULLED", "Annulled"


class Person(TimeStampedModel):
    """A human known to the church. Membership is a status, not a separate model."""

    # Fields the follow-up queue chases when blank (spec section 6.3).
    TRACKED_FIELDS = (
        "date_of_birth",
        "mobile_number",
        "email",
        "home_address",
        "civil_status",
    )

    # Cleared by purge_stale_contacts two years after transfer or death.
    CONTACT_FIELDS = (
        "mobile_number",
        "email",
        "home_address",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "emergency_contact_number",
    )

    member_no = models.CharField(max_length=12, unique=True, null=True, blank=True)

    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=20, blank=True)
    nickname = models.CharField(
        max_length=60, blank=True, help_text="The name this person actually goes by."
    )

    date_of_birth = models.DateField(null=True, blank=True)
    place_of_birth = models.CharField(max_length=200, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    civil_status = models.CharField(
        max_length=12, choices=CivilStatus.choices, blank=True
    )
    nationality = models.CharField(max_length=60, default="Filipino", blank=True)

    home_address = models.TextField(blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    membership_status = models.CharField(
        max_length=12,
        choices=MembershipStatus.choices,
        default=MembershipStatus.RELATED,
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    date_filed = models.DateField(
        null=True, blank=True, help_text="The date written on the paper form."
    )
    date_became_member = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="approved"
    )
    date_of_death = models.DateField(null=True, blank=True)

    guardian = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="wards"
    )
    guardian_relationship = models.CharField(max_length=60, blank=True)

    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True)

    consent_given = models.BooleanField(default=False)
    consent_date = models.DateField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, blank=True)
    greeting_opt_out = models.BooleanField(
        default=False, help_text="Suppress this person from birthday and anniversary lists."
    )

    has_missing_data = models.BooleanField(default=False, editable=False)
    follow_up_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("last_name", "first_name")
        verbose_name_plural = "people"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_status = instance.membership_status
        return instance

    def refresh_from_db(self, using=None, fields=None):
        super().refresh_from_db(using=using, fields=fields)
        # refresh_from_db copies field values from a separate instance and never
        # calls from_db on self, so the status shadow has to be resynced by hand.
        # Only when the status was actually refetched: a partial refresh must not
        # discard an unsaved in-memory status change.
        if fields is None or "membership_status" in fields:
            self._loaded_status = self.membership_status

    def __str__(self):
        return f"{self.full_name} ({self.member_no})" if self.member_no else self.full_name

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name, self.suffix]
        return " ".join(part for part in parts if part)

    @property
    def missing_fields(self) -> list[str]:
        return [name for name in self.TRACKED_FIELDS if not getattr(self, name)]

    def clean(self):
        super().clean()
        loaded = getattr(self, "_loaded_status", None)
        becoming_member = (
            loaded is not None
            and loaded != MembershipStatus.MEMBER
            and self.membership_status == MembershipStatus.MEMBER
        )
        if becoming_member and self.approved_by_id is None:
            raise ValidationError(
                {
                    "approved_by": (
                        "Record who accepted this person into membership. "
                        "The Board or Pastor decides; the system only records it."
                    )
                }
            )

    def save(self, *args, **kwargs):
        loaded = getattr(self, "_loaded_status", None)
        if loaded != self.membership_status:
            self.status_changed_at = timezone.now()
        self.has_missing_data = bool(self.missing_fields)
        super().save(*args, **kwargs)
        self._loaded_status = self.membership_status
