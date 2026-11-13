"""Check submitted identity without returning another person's private fields."""
import unicodedata

from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.models import LoginAttempt
from imports.models import StagedPerson, StagedPersonStatus
from imports.services import _given_name_tokens, _names_are_compatible
from people.models import Person


def _name(value):
    return "".join(ch for ch in unicodedata.normalize("NFKC", value or "").casefold() if ch.isalnum())


def lock_registration_identity(data):
    """Serialize surname matches, including initials; caller holds atomic()."""
    identity = _name(data.get("last_name"))
    key = "reg:identity:" + salted_hmac("aegis.registration.identity", identity, algorithm="sha256").hexdigest()
    LoginAttempt.objects.get_or_create(key=key, defaults={"window_started_at": timezone.now()})
    lock = LoginAttempt.objects.select_for_update().get(key=key)
    # A stale-counter cleanup must not remove an identity lock that is
    # currently in use by a registration transaction.
    lock.save(update_fields=["updated_at"])
    return lock


def registration_match(data):
    """Return a generic result, never a person ID, contact detail, or stored date."""
    last = _name(data.get("last_name"))
    first = _given_name_tokens(data.get("first_name", ""), data.get("middle_name", ""))
    dob = data.get("date_of_birth")
    if not first or not last:
        return None
    submitted_dob = dob.isoformat() if dob else None
    candidates = list(Person.objects.values("first_name", "middle_name", "last_name", "suffix", "date_of_birth"))
    pending = StagedPerson.objects.filter(status=StagedPersonStatus.PENDING).only("raw_data", "edited_data")
    candidates.extend({**row.effective_data, "pending": True} for row in pending)
    possible = []
    for candidate in candidates:
        if _name(candidate.get("last_name")) != last:
            continue
        if not _names_are_compatible(first, _given_name_tokens(candidate.get("first_name", ""), candidate.get("middle_name", ""))):
            continue
        if data.get("suffix") and candidate.get("suffix") and _name(data["suffix"]) != _name(candidate["suffix"]):
            continue
        stored = candidate.get("date_of_birth")
        stored_dob = stored.isoformat() if hasattr(stored, "isoformat") else (stored or None)
        if submitted_dob and stored_dob and submitted_dob != stored_dob:
            continue  # A namesake with a different known birthday can register.
        if submitted_dob and stored_dob:
            if candidate.get("pending"):
                return {"status": "pending", "message": "A registration matching these details is already waiting for review. Please speak to the Secretariat if you need to make a correction."}
            return {"status": "existing", "message": "These details match an existing member record. Please speak to the Secretariat to update your record instead of registering again."}
        possible.append(candidate)
    if possible:
        if not submitted_dob and any(c.get("date_of_birth") for c in possible):
            return {"status": "need_birth_date", "message": "A record with this name may already exist. Please add your date of birth so we can check, or speak to the Secretariat if you prefer not to provide it."}
        return {"status": "possible", "message": "A record or registration with this name may already exist, but the birth date cannot be confirmed. Please speak to the Secretariat before submitting another registration."}
    return None
