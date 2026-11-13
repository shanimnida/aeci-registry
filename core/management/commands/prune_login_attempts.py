from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import LoginAttempt


class Command(BaseCommand):
    help = "Remove expired login counters more than a day old."

    def handle(self, *args, **options):
        count, _ = LoginAttempt.objects.filter(
            updated_at__lt=timezone.now() - timedelta(days=1)
        ).delete()
        self.stdout.write(f"Removed {count} expired login counters.")
