from collections import Counter

from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """One uploaded JSON file from the AI transcription workflow.

    The AI never writes to the register (docs/IMPORT_TEMPLATE.md) — this
    model and StagedPerson below are the holding area between "the AI
    produced a file" and "a person exists in people.Person". Nothing here
    ever becomes a Person without an explicit per-row approval.
    """

    source_filename = models.CharField(max_length=255, blank=True)
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=(
            "SHA-256 of the uploaded file's bytes. IMPORTANT 7: the simplest "
            "reliable way to notice a re-upload of the same file -- the "
            "filename alone changes too easily to trust."
        ),
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_batches",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        label = self.source_filename or "import"
        return f"{label} — {self.uploaded_at:%Y-%m-%d %H:%M}"

    def counts(self) -> dict:
        return status_counts(self.rows.all())

    def next_pending(self):
        return self.rows.filter(status=StagedPersonStatus.PENDING).order_by("sequence").first()


class StagedPersonStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


def status_counts(queryset) -> dict:
    """Tally a StagedPerson queryset by status. Shared by ImportBatch.counts
    (scoped to one batch) and the cross-batch review queue (imports/admin.py's
    queue_view), which needs the identical total/pending/approved/rejected
    shape but scoped to whatever batch filter -- or none -- is active there.
    """
    tally = Counter(queryset.values_list("status", flat=True))
    total = sum(tally.values())
    return {
        "total": total,
        "pending": tally.get(StagedPersonStatus.PENDING, 0),
        "approved": tally.get(StagedPersonStatus.APPROVED, 0),
        "rejected": tally.get(StagedPersonStatus.REJECTED, 0),
    }


class StagedPerson(models.Model):
    """One entry from the uploaded JSON array, not yet — or never — a Person.

    `raw_data` is exactly what the AI produced for this entry and is never
    modified. `edited_data` holds the reviewer's corrections once they save
    or attempt to approve the row, so a failed approval does not lose the
    reviewer's work. Nothing about this model touches people.Person until
    a human explicitly approves it (see imports.services).
    """

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    sequence = models.PositiveIntegerField(help_text="Position in the uploaded file.")
    raw_data = models.JSONField(help_text="Exactly what the AI produced for this entry.")
    edited_data = models.JSONField(
        null=True,
        blank=True,
        help_text="The reviewer's corrections, if any. Falls back to raw_data when absent.",
    )
    status = models.CharField(
        max_length=10, choices=StagedPersonStatus.choices, default=StagedPersonStatus.PENDING
    )
    error_message = models.TextField(
        blank=True, help_text="Why the last approval attempt was refused, if it was."
    )
    created_person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("batch_id", "sequence")
        constraints = [
            models.UniqueConstraint(fields=["batch", "sequence"], name="unique_sequence_per_batch")
        ]

    def __str__(self):
        data = self.effective_data
        name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        return name or data.get("source_image") or f"row {self.sequence}"

    @property
    def effective_data(self) -> dict:
        return self.edited_data if self.edited_data is not None else self.raw_data
