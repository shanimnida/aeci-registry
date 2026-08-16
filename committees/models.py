from django.db import models

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
