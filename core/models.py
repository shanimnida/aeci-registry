from django.conf import settings
from django.db import models


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
            )
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year or 'perpetual'}: {self.last_value}"
