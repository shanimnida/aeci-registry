from datetime import timedelta
from ipaddress import ip_address
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from core.models import LoginAttempt
from imports.models import ImportBatch, StagedPerson
from imports.registration_duplicates import lock_registration_identity, registration_match
from imports.registration_forms import (
    CONSENT_VERSION, GREETING_NOTICE, NOTICE, TOKEN_SALT,
    MemberRegistrationForm, RegistrationChildFormSet,
)


def _attempt_allowed(request):
    try:
        address = str(ip_address(request.META.get("REMOTE_ADDR", "")))
    except ValueError:
        address = "unknown"
    scopes = [("ip", address, settings.REGISTRATION_IP_LIMIT),
              ("session", request.session["registration_key"], settings.REGISTRATION_SESSION_LIMIT)]
    now = timezone.now()
    with transaction.atomic():
        buckets = []
        for scope, value, limit in scopes:
            key = f"reg:{scope}:" + salted_hmac("aegis.registration", value, algorithm="sha256").hexdigest()
            LoginAttempt.objects.get_or_create(key=key, defaults={"window_started_at": now})
            bucket = LoginAttempt.objects.select_for_update().get(key=key)
            if bucket.window_started_at + timedelta(hours=1) <= now:
                bucket.failures = 0
                bucket.window_started_at = now
            buckets.append((bucket, limit))
        if any(bucket.failures >= limit for bucket, limit in buckets):
            return False
        for bucket, _ in buckets:
            bucket.failures += 1
            bucket.save()
    return True


def _entry(form, children):
    data = form.cleaned_data
    today = timezone.localdate().isoformat()
    entry = {name: value for name, value in data.items() if name not in {
        "submission_token", "contact_website", "committees",
    }}
    for field in ("date_of_birth", "date_of_marriage"):
        entry[field] = data[field].isoformat() if data.get(field) else None
    entry.update({
        "committees": [committee.name for committee in data["committees"]],
        "children": [{"full_name": child["full_name"],
                      "date_of_birth": child["date_of_birth"].isoformat() if child.get("date_of_birth") else None}
                     for child in children.cleaned_data if child.get("full_name")],
        "source_image": "", "member_no": "", "form_version": "v3",
        "date_filed": today, "certification_date": today,
        "confidence": "high", "uncertain_fields": [],
        "_registration": {
            "submitted_at": timezone.now().isoformat(),
            "consent_version": CONSENT_VERSION,
            "privacy_notice": list(NOTICE), "greeting_notice": GREETING_NOTICE,
            "consent_statement": MemberRegistrationForm.base_fields["consent_given"].label,
            "greeting_statement": MemberRegistrationForm.base_fields["public_greeting_consent"].label,
        },
    })
    # Choice fields use an empty string on screen, while the review/import
    # representation uses null for an unanswered enum.
    for field in ("gender", "civil_status"):
        entry[field] = entry[field] or None
    return entry


@never_cache
@require_http_methods(["GET", "POST"])
def member_registration(request):
    if not request.session.get("registration_key"):
        request.session["registration_key"] = uuid4().hex
    session_key = request.session["registration_key"]
    data = request.POST if request.method == "POST" else None
    form = MemberRegistrationForm(data, session_key=session_key)
    children = RegistrationChildFormSet(data, prefix="children")
    status = 200
    if request.method == "POST":
        # Check the signed form token first, so malformed requests cannot
        # allocate unlimited per-session counter rows.
        form_valid = form.is_valid()
        checking = request.POST.get("action") == "check_record"
        children_valid = children.is_valid() if not checking else True
        submission_id = form.cleaned_data.get("submission_token")
        if submission_id and ImportBatch.objects.filter(website_submission_id=submission_id).exists():
            if checking:
                return JsonResponse({"status": "pending", "message": "This registration has already been received for review."})
            return redirect("member_registration_received")
        if submission_id and not _attempt_allowed(request):
            if checking:
                response = JsonResponse({"status": "limited", "message": "Too many checks from this connection. Please try again in an hour, or speak to the Secretariat."}, status=429)
                response["Retry-After"] = "3600"
                return response
            form.add_error(None, "Too many submissions from this connection. Please try again in an hour, or speak to the Secretariat.")
            status = 429
        else:
            match = registration_match(form.cleaned_data) if form_valid else None
            if checking:
                if not form_valid:
                    return JsonResponse({"status": "invalid", "message": "Enter your first and last name, check any date entered, and give privacy consent before checking."}, status=400)
                return JsonResponse(match or {"status": "clear", "message": "We did not find a matching record with these details. You can continue with the form; the Secretariat will review your registration."})
            if match:
                form.add_error(None, match["message"])
                form_valid = False
        if status != 429 and form_valid and children_valid:
            with transaction.atomic():
                lock_registration_identity(form.cleaned_data)
                if ImportBatch.objects.filter(website_submission_id=submission_id).exists():
                    return redirect("member_registration_received")
                # Another browser can submit while the form is open. Check
                # again under the identity lock before creating a new row.
                concurrent_match = registration_match(form.cleaned_data)
                if concurrent_match:
                    form.add_error(None, concurrent_match["message"])
                else:
                    batch = ImportBatch.objects.create(
                        website_submission_id=submission_id,
                        source_filename="Website registration",
                    )
                    StagedPerson.objects.create(
                        batch=batch, sequence=0, raw_data=_entry(form, children),
                        source_key=f"website:{submission_id}",
                    )
                    return redirect("member_registration_received")
    else:
        form.initial["submission_token"] = signing.dumps(
            {"id": str(uuid4()), "session": session_key}, salt=TOKEN_SALT,
        )
    # Tokens invalidated by expiry/session loss are replaced without losing
    # the submitted personal fields. A fresh submit must pass validation again.
    if request.method == "POST" and "submission_token" in form.errors:
        refreshed = form.data.copy()
        refreshed["submission_token"] = signing.dumps(
            {"id": str(uuid4()), "session": session_key}, salt=TOKEN_SALT,
        )
        form.data = refreshed
    response = render(request, "registration/form.html", {
        "form": form, "children": children, "privacy_notice": NOTICE,
        "greeting_notice": GREETING_NOTICE, "consent_version": CONSENT_VERSION,
    }, status=status)
    response["X-Robots-Tag"] = "noindex, nofollow"
    if status == 429:
        response["Retry-After"] = "3600"
    return response


@never_cache
@require_safe
def member_registration_received(request):
    response = render(request, "registration/received.html")
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
