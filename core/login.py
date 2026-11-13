"""Database-backed throttling shared by every Gunicorn process."""

from datetime import timedelta
from ipaddress import ip_address
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.models import LoginAttempt


LOCKED_MESSAGE = "Too many unsuccessful login attempts. Please try again in 15 minutes."


def _key(scope, value):
    digest = salted_hmac("aegis.login." + scope, value, algorithm="sha256").hexdigest()
    return f"{scope}:{digest}"


class LoginRateLimitMixin:
    def clean(self):
        username = unicodedata.normalize("NFKC", self.data.get("username", "")).casefold()
        # Forwarded headers are client-controlled unless a proxy explicitly
        # sanitizes them. The socket peer is the safe default (a shared proxy
        # may share the IP budget, while account limits always remain separate).
        try:
            address = str(ip_address(self.request.META.get("REMOTE_ADDR", "")))
        except ValueError:
            address = "unknown"
        account_key = _key("account", username)
        keys = [(account_key, settings.LOGIN_ACCOUNT_FAILURE_LIMIT),
                (_key("ip", address), settings.LOGIN_IP_FAILURE_LIMIT)]
        now = timezone.now()
        window = timedelta(minutes=15)
        error = None
        cleaned = None
        # Raising a validation error inside this block would roll back the
        # failed-attempt counters. Save the error and raise after committing.
        with transaction.atomic():
            buckets = []
            for key, limit in sorted(keys):
                LoginAttempt.objects.get_or_create(
                    key=key, defaults={"window_started_at": now}
                )
                bucket = LoginAttempt.objects.select_for_update().get(key=key)
                if bucket.locked_until is not None and bucket.locked_until <= now:
                    bucket.failures = 0
                    bucket.locked_until = None
                    bucket.window_started_at = now
                elif bucket.locked_until is None and bucket.window_started_at + window <= now:
                    bucket.failures = 0
                    bucket.window_started_at = now
                buckets.append((bucket, limit))
            if any(b.locked_until is not None and b.locked_until > now for b, _ in buckets):
                error = ValidationError(LOCKED_MESSAGE, code="rate_limited")
            else:
                try:
                    cleaned = super().clean()
                except ValidationError as exc:
                    error = exc
                failed = error is not None or bool(self._errors)
                for bucket, limit in buckets:
                    if failed:
                        bucket.failures += 1
                        if bucket.failures >= limit:
                            bucket.locked_until = now + window
                    elif bucket.key == account_key:
                        bucket.failures = 0
                        bucket.locked_until = None
                        bucket.window_started_at = now
                    bucket.save()
        if error is not None:
            raise error
        return cleaned


def protect_admin_login(site):
    """Keep the theme's login widgets and Django's staff/password checks."""
    from django.contrib.admin.forms import AdminAuthenticationForm

    base = site.login_form or AdminAuthenticationForm
    if not issubclass(base, LoginRateLimitMixin):
        site.login_form = type("AegisLoginForm", (LoginRateLimitMixin, base), {})
