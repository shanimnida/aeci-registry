from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.capitalization import capitalize_suffix, capitalize_words
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

    # Normalized (title-cased, if currently shouting) on every save -- see
    # core.capitalization. member_no, phone numbers, control numbers and
    # email are deliberately absent: an identifier or an email address is
    # not a name, and lower-casing "MEM-0001" or an email would corrupt it.
    # suffix is handled separately, via capitalize_suffix -- see save().
    CAPITALIZED_FIELDS = (
        "last_name",
        "first_name",
        "middle_name",
        "nickname",
        "place_of_birth",
        "home_address",
        "nationality",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "guardian_relationship",
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

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
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
        # IMPORTANT 4 (2026-08-16 import fixes): docs/IMPORT_TEMPLATE.md tells
        # the transcribing AI to record an impossible date exactly as written
        # rather than "fix" it, and promises AEGIS checks calendar validity
        # itself once a reviewer approves. That promise was false for anything
        # Django's own date parser accepts as a real date -- a birth year of
        # 2099 is a syntactically fine date and passed full_clean() untouched.
        # Checked here, on the model, rather than only in imports/services.py,
        # so every write path shares it: the ordinary Person admin form, the
        # import path, and any future one. Deliberately narrow: only a date
        # that is *impossible* (in the future) is refused. A birth year that
        # is merely improbable is not -- decades of paper backlog, hand-typed
        # by whoever filled the form, must stay encodable, or the backlog
        # itself becomes un-encodable.
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError(
                {"date_of_birth": "Date of birth cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        for field_name in self.CAPITALIZED_FIELDS:
            setattr(self, field_name, capitalize_words(getattr(self, field_name)))
        self.suffix = capitalize_suffix(self.suffix)
        loaded = getattr(self, "_loaded_status", None)
        if loaded != self.membership_status:
            self.status_changed_at = timezone.now()
        self.has_missing_data = bool(self.missing_fields)
        super().save(*args, **kwargs)
        self._loaded_status = self.membership_status


class HouseholdRole(models.TextChoices):
    HEAD = "HEAD", "Head"
    SPOUSE = "SPOUSE", "Spouse"
    CHILD = "CHILD", "Child"
    OTHER = "OTHER", "Other"


class Household(TimeStampedModel):
    name = models.CharField(max_length=200, help_text='For example, "Malong Family".')
    address = models.TextField(blank=True)
    date_of_marriage = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        # IMPORTANT 4: the marriage-date half of "a date of marriage in the
        # future" that docs/IMPORT_TEMPLATE.md now promises AEGIS refuses.
        # Self-contained -- it only needs this row's own field -- unlike the
        # "before either spouse's own birth date" half, which needs a
        # specific person and belongs on HouseholdMember.clean() below,
        # where household and person are both already in hand.
        if self.date_of_marriage and self.date_of_marriage > timezone.localdate():
            raise ValidationError(
                {"date_of_marriage": "Date of marriage cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        self.name = capitalize_words(self.name)
        super().save(*args, **kwargs)


class HouseholdMember(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="members"
    )
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="household_memberships"
    )
    role = models.CharField(max_length=10, choices=HouseholdRole.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "person"], name="unique_person_per_household"
            )
        ]

    def __str__(self):
        return f"{self.person.full_name} — {self.get_role_display()}"

    def clean(self):
        super().clean()
        # IMPORTANT 4 (2026-08-16 import fixes): the other two "impossible,
        # not merely improbable" date checks docs/IMPORT_TEMPLATE.md promises.
        # Both compare two different rows' dates against each other, which
        # neither Person.clean() nor Household.clean() can do alone -- this
        # join model is where a household, a role and a specific person are
        # all in hand at once, and it is already full_clean()-ed on every
        # creation path (the ordinary admin inline included), so putting the
        # checks here protects every write path, not just imports/services.py.
        if not (self.household_id and self.person_id):
            return
        if self.role == HouseholdRole.CHILD:
            child_dob = self.person.date_of_birth
            if child_dob:
                head = (
                    self.household.members.filter(role=HouseholdRole.HEAD)
                    .exclude(pk=self.pk)
                    .select_related("person")
                    .first()
                )
                if head and head.person.date_of_birth and child_dob < head.person.date_of_birth:
                    raise ValidationError(
                        {
                            "person": (
                                f"{self.person.full_name} (born {child_dob}) would be older "
                                f"than the household head, {head.person.full_name} (born "
                                f"{head.person.date_of_birth}) -- check the date of birth."
                            )
                        }
                    )
        elif self.role in (HouseholdRole.HEAD, HouseholdRole.SPOUSE):
            marriage_date = self.household.date_of_marriage
            birth_date = self.person.date_of_birth
            if marriage_date and birth_date and marriage_date < birth_date:
                raise ValidationError(
                    {
                        "household": (
                            f"The date of marriage ({marriage_date}) is before "
                            f"{self.person.full_name}'s own date of birth ({birth_date})."
                        )
                    }
                )
