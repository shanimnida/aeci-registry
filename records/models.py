from django.conf import settings
from django.db import models


class FormType(models.TextChoices):
    MEMBER_PROFILING = "MEMBER_PROFILING", "Member Profiling Form"
    EARF = "EARF", "Event and Activity Request Form"
    FR = "FR", "Fund Request Form"
    RB = "RB", "Fund Reimbursement Form"
    CDV = "CDV", "Cash Disbursement Voucher"
    MOM = "MOM", "Minutes of Meeting"
    OTHER = "OTHER", "Other"


class FormScan(models.Model):
    """A photograph of a paper form, kept as evidence and for reference."""

    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scans",
    )
    form_type = models.CharField(max_length=20, choices=FormType.choices)
    file = models.FileField(upload_to="scans/%Y/%m/", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        who = self.person.full_name if self.person else "unlinked"
        return f"{self.get_form_type_display()} — {who}"


class AccessLog(models.Model):
    """Who looked at whom.

    django-simple-history records changes; it does not record reads. Under
    RA 10173 this is the log that answers a member asking how their address
    circulated. Spec section 5.2.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    person = models.ForeignKey(
        "people.Person", null=True, blank=True, on_delete=models.CASCADE
    )
    report = models.CharField(
        max_length=120,
        blank=True,
        help_text="Set instead of person when a whole list was viewed.",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-timestamp",)

    def __str__(self):
        target = self.person.full_name if self.person else self.report
        return f"{self.user} viewed {target}"

    @classmethod
    def record(cls, user, person=None, report="", ip=None):
        return cls.objects.create(
            user=user, person=person, report=report, ip_address=ip
        )
