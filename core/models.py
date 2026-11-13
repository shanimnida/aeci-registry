from django.conf import settings
from django.db import models
from django.db.models import Q


class LoginAttempt(models.Model):
    """Shared login counters. Keys contain HMACs, never usernames or IPs."""

    key = models.CharField(max_length=80, primary_key=True)
    failures = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        # Internal counters, never editable through a staff role or admin.
        default_permissions = ()


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True


class ControlNumberSequence(models.Model):
    """One row per (prefix, year). Year is NULL for sequences that never reset."""

    prefix = models.CharField(max_length=8)
    year = models.IntegerField(null=True, blank=True)
    last_value = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "year"], name="unique_prefix_year"
            ),
            # PostgreSQL's unique index treats every NULL as distinct from
            # every other NULL, so the constraint above never fires for
            # year=None — exactly the case perpetual sequences (MEM-) use.
            # A partial unique index scoped to the NULL rows closes that
            # gap: at most one row per prefix may have year IS NULL.
            models.UniqueConstraint(
                fields=["prefix"],
                condition=Q(year__isnull=True),
                name="unique_prefix_when_year_null",
            ),
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year or 'perpetual'}: {self.last_value}"
