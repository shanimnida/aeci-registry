from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core import signing
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from committees.models import Committee, CommitteeMembership
from imports.forms import children_initial, initial_from_data
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.registration_forms import CONSENT_VERSION, NOTICE, TOKEN_SALT
from people.models import Person


pytestmark = pytest.mark.django_db
URL = "/register/"


def payload(client, **changes):
    response = client.get(URL)
    assert response.status_code == 200
    data = {
        "submission_token": response.context["form"]["submission_token"].value(),
        "first_name": "Website", "last_name": "Synthetic", "consent_given": "on",
        "date_of_birth": "1990-05-09",
        "children-TOTAL_FORMS": "1", "children-INITIAL_FORMS": "0",
        "children-MIN_NUM_FORMS": "0", "children-MAX_NUM_FORMS": "10",
    }
    data.update(changes)
    return data


def test_public_form_is_branded_and_does_not_expose_private_records(client):
    Person.objects.create(first_name="PrivateName", last_name="NeverPublic", email="private@example.com")
    response = client.get(URL)
    body = response.content.decode()
    assert "Member registration" in body
    assert "Avdei Elohim Church" in body
    assert "PrivateName" not in body and "private@example.com" not in body
    assert "no-store" in response["Cache-Control"]
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert "Grievance and Reconciliation" not in body
    assert 'name="membership_status"' not in body
    assert 'name="member_no"' not in body
    assert not response.context["form"].fields["public_greeting_consent"].initial


def test_minimal_consenting_registration_is_staged_without_creating_member_or_login(client):
    data = payload(client, date_of_birth="")
    response = client.post(URL, data)
    assert response.status_code == 302
    assert response.url == reverse("member_registration_received")
    assert Person.objects.count() == User.objects.count() == CommitteeMembership.objects.count() == 0
    row = StagedPerson.objects.get()
    assert row.status == StagedPersonStatus.PENDING
    assert row.batch.website_submission_id is not None
    assert row.batch.uploaded_by is None
    assert row.raw_data["consent_given"] is True
    assert row.raw_data["public_greeting_consent"] is False
    assert row.raw_data["_registration"]["consent_version"] == CONSENT_VERSION
    assert row.raw_data["_registration"]["privacy_notice"] == [list(item) for item in NOTICE]


def test_all_fields_children_and_separate_greeting_consent_are_preserved(client):
    committee = Committee.objects.get(code="sunshine")
    data = payload(client, middle_name="Example", nickname="Web", gender="FEMALE",
                   mobile_number="0917 000 0000", email="synthetic@example.com",
                   spouse_name="Spouse Synthetic", date_of_marriage="2015-01-01",
                   public_greeting_consent="on", committees=[str(committee.pk)],
                   notes="Please contact me after Sunday service.")
    data.update({"children-0-full_name": "Child Synthetic", "children-0-date_of_birth": "2020-01-01"})
    assert client.post(URL, data).status_code == 302
    raw = StagedPerson.objects.get().raw_data
    assert raw["children"] == [{"full_name": "Child Synthetic", "date_of_birth": "2020-01-01"}]
    assert raw["committees"] == ["Sunshine"]
    assert raw["public_greeting_consent"] is True
    assert raw["notes"] == data["notes"]


@pytest.mark.parametrize("changes", [
    {"consent_given": ""}, {"first_name": ""}, {"last_name": ""},
    {"email": "invalid-email"}, {"gender": "invented"},
    {"date_of_birth": "2026-02-30"}, {"first_name": "X" * 101},
    {"contact_website": "spam.example"}, {"children-0-date_of_birth": "2020-01-01"},
    {"children-TOTAL_FORMS": "11"}, {"children-TOTAL_FORMS": "invalid"},
    {"date_of_marriage": "1980-01-01"},
])
def test_invalid_submission_is_rejected_and_preserves_entered_fields(client, changes):
    data = payload(client, **changes)
    response = client.post(URL, data)
    assert response.status_code == 200
    assert "Please check your details" in response.content.decode()
    assert not ImportBatch.objects.exists()
    assert response.context["form"].data["last_name"] == data["last_name"]


def test_future_dates_are_rejected(client):
    data = payload(client, date_of_birth=(timezone.localdate() + timedelta(days=1)).isoformat())
    response = client.post(URL, data)
    assert "today or earlier" in response.content.decode()
    assert not StagedPerson.objects.exists()


@pytest.mark.parametrize("kind", ["appointed", "inactive", "too_many"])
def test_only_up_to_two_active_self_selectable_committees_are_accepted(client, kind):
    if kind == "appointed":
        chosen = [Committee.objects.get(code="grievance-and-reconciliation").pk]
    elif kind == "inactive":
        committee = Committee.objects.get(code="sunshine")
        committee.is_active = False
        committee.save()
        chosen = [committee.pk]
    else:
        chosen = list(Committee.objects.filter(is_self_selectable=True).values_list("pk", flat=True)[:3])
    response = client.post(URL, payload(client, committees=chosen))
    assert response.status_code == 200
    assert response.context["form"].errors.get("committees")
    assert not StagedPerson.objects.exists()


def test_forged_privileged_fields_have_no_effect(client):
    data = payload(client, membership_status="MEMBER", member_no="MEM-9999", is_superuser="on", user="1")
    assert client.post(URL, data).status_code == 302
    assert "membership_status" not in StagedPerson.objects.get().raw_data
    assert StagedPerson.objects.get().raw_data["member_no"] == ""
    assert not User.objects.exists()


def test_repeated_post_uses_one_submission_and_returns_same_confirmation(client):
    data = payload(client)
    assert client.post(URL, data).status_code == 302
    data["first_name"] = "A second click must not edit the first submission"
    assert client.post(URL, data).status_code == 302
    assert StagedPerson.objects.count() == ImportBatch.objects.count() == 1
    assert StagedPerson.objects.get().raw_data["first_name"] == "Website"


def test_tampered_token_and_another_browser_token_cannot_submit(client):
    data = payload(client)
    other = Client()
    assert other.post(URL, data).status_code == 200
    data["submission_token"] += "tampered"
    assert client.post(URL, data).status_code == 200
    assert not StagedPerson.objects.exists()


def test_expired_token_is_replaced_without_losing_entered_values(client, monkeypatch):
    import time
    data = payload(client)
    original = time.time
    with monkeypatch.context() as patch:
        patch.setattr(time, "time", lambda: original() - 9 * 3600)
        data["submission_token"] = signing.dumps(
            {"id": str(uuid4()), "session": client.session["registration_key"]}, salt=TOKEN_SALT,
        )
    response = client.post(URL, data)
    assert not StagedPerson.objects.exists()
    assert response.context["form"].data["first_name"] == "Website"
    refreshed = response.context["form"]["submission_token"].value()
    assert refreshed != data["submission_token"]
    data["submission_token"] = refreshed
    assert client.post(URL, data).status_code == 302


def test_csrf_and_public_body_size_limit_are_enforced():
    client = Client(enforce_csrf_checks=True)
    data = payload(client)
    assert client.post(URL, data).status_code == 403
    assert client.post(URL, {"notes": "X" * 70000}).status_code == 413
    assert not StagedPerson.objects.exists()


def test_ip_rate_limit_ignores_forged_forwarding_headers(client, settings):
    settings.REGISTRATION_IP_LIMIT = 1
    data = payload(client, action="check_record")
    assert client.post(URL, data, HTTP_X_FORWARDED_FOR="192.0.2.1").status_code == 200
    response = client.post(URL, data, HTTP_X_FORWARDED_FOR="192.0.2.2")
    assert response.status_code == 429
    assert response["Retry-After"] == "3600"
    assert not StagedPerson.objects.exists()


def test_existing_record_notifies_member_without_returning_private_details(client):
    Person.objects.create(first_name="Website", last_name="Synthetic", date_of_birth="1990-05-09",
                          mobile_number="09179999999", email="private@example.com", home_address="Private address")
    data = payload(client, action="check_record")
    response = client.post(URL, data)
    assert response.json()["status"] == "existing"
    assert "existing member record" in response.json()["message"]
    for private in ("09179999999", "private@example.com", "Private address", "1990-05-09"):
        assert private not in response.content.decode()
    data.pop("action")
    assert client.post(URL, data).status_code == 200
    assert not StagedPerson.objects.exists()


def test_same_name_requests_birth_date_and_namesake_with_different_date_can_register(client):
    Person.objects.create(first_name="Website", last_name="Synthetic", date_of_birth="1980-01-01")
    data = payload(client, action="check_record", date_of_birth="")
    assert client.post(URL, data).json()["status"] == "need_birth_date"
    data["date_of_birth"] = "1990-05-09"
    assert client.post(URL, data).json()["status"] == "clear"
    data.pop("action")
    assert client.post(URL, data).status_code == 302


def test_existing_incomplete_record_is_flagged_for_secretariat(client):
    Person.objects.create(first_name="Website", last_name="Synthetic")
    response = client.post(URL, payload(client, action="check_record"))
    assert response.json()["status"] == "possible"
    assert not StagedPerson.objects.exists()


def test_case_spacing_middle_initial_and_family_name_punctuation_are_matched(client):
    Person.objects.create(first_name="Website", middle_name="Example", last_name="Dela Cruz", date_of_birth="1990-05-09")
    response = client.post(URL, payload(client, first_name="website", middle_name="E.", last_name="DELA-CRUZ", action="check_record"))
    assert response.json()["status"] == "existing"


def test_new_browser_is_not_allowed_to_duplicate_pending_registration(client):
    assert client.post(URL, payload(client)).status_code == 302
    other = Client()
    data = payload(other, action="check_record")
    assert other.post(URL, data).json()["status"] == "pending"
    data.pop("action")
    assert other.post(URL, data).status_code == 200
    assert StagedPerson.objects.count() == 1


def test_check_requires_names_consent_and_signed_form_and_never_stages(client):
    data = payload(client, action="check_record", consent_given="")
    assert client.post(URL, data).status_code == 400
    data["consent_given"] = "on"
    assert client.post(URL, data).json()["status"] == "clear"
    assert not StagedPerson.objects.exists()


def test_review_can_approve_submission_and_preserve_consent_notes_and_family(client):
    data = payload(client, notes="Member message for the Secretariat", public_greeting_consent="on")
    data.update({"children-0-full_name": "Child Synthetic", "children-0-date_of_birth": "2020-01-01"})
    assert client.post(URL, data).status_code == 302
    row = StagedPerson.objects.get()
    admin = User.objects.create_superuser("registration-reviewer", password="test-password")
    client.force_login(admin)
    review_url = reverse("admin:imports_importbatch_review", args=[row.batch_id, row.pk])
    body = client.get(review_url).content.decode()
    assert "Website registration" in body and "AI confidence" not in body
    assert "Member message for the Secretariat" in body
    post = initial_from_data(row.raw_data)
    post.update({"action": "approve", "children-TOTAL_FORMS": "1", "children-INITIAL_FORMS": "1",
                 "children-MIN_NUM_FORMS": "0", "children-MAX_NUM_FORMS": "1000",
                 "children-0-full_name": "Child Synthetic", "children-0-date_of_birth": "2020-01-01"})
    post = {key: ("" if value is None else value) for key, value in post.items()}
    assert client.post(review_url, post).status_code == 302
    row.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    person = Person.objects.get(first_name="Website")
    assert person.consent_version == CONSENT_VERSION
    assert person.public_greeting_consent is True
    assert person.notes == "Member message for the Secretariat"
    assert Person.objects.filter(first_name="Child").exists()


def test_submission_is_private_and_confirmation_contains_no_member_information(client):
    assert client.post(URL, payload(client)).status_code == 302
    response = client.get(reverse("member_registration_received"))
    assert "Synthetic" not in response.content.decode()
    assert "Website" not in response.content.decode()
    row = StagedPerson.objects.get()
    url = reverse("admin:imports_importbatch_review", args=[row.batch_id, row.pk])
    assert client.get(url).status_code == 302


def test_login_page_links_to_member_registration(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
    assert 'href="/register/"' in response.content.decode()


def test_submitted_markup_is_escaped_on_the_staff_review_page(client):
    data = payload(client, notes='<script>alert("synthetic")</script>')
    assert client.post(URL, data).status_code == 302
    row = StagedPerson.objects.get()
    admin = User.objects.create_superuser("markup-reviewer", password="test-password")
    client.force_login(admin)
    url = reverse("admin:imports_importbatch_review", args=[row.batch_id, row.pk])
    body = client.get(url).content.decode()
    assert '<script>alert("synthetic")</script>' not in body
    assert "&lt;script&gt;" in body


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_simultaneous_registrations_of_same_member_stage_only_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from django.db import connections
    from imports import registration_views

    clients = [Client(), Client()]
    posts = [payload(client) for client in clients]
    real_match = registration_views.registration_match
    barrier = Barrier(2)
    state = local()
    def matched_together(data):
        result = real_match(data)
        if not getattr(state, "synced", False):
            state.synced = True
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(registration_views, "registration_match", matched_together)
    def submit(index):
        try:
            return clients[index].post(URL, posts[index]).status_code
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 302]
    assert StagedPerson.objects.count() == ImportBatch.objects.count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_simultaneous_reuse_of_same_signed_form_stages_once():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connections

    browser = Client()
    data = payload(browser)
    clients = [Client(), Client()]
    for client in clients:
        client.cookies = browser.cookies.copy()
    barrier = Barrier(2)
    def submit(index):
        try:
            barrier.wait(timeout=10)
            return clients[index].post(URL, data).status_code
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(status in (200, 302) for status in pool.map(submit, range(2)))
    assert StagedPerson.objects.count() == ImportBatch.objects.count() == 1


def test_invalid_form_can_be_corrected_and_session_budget_expires(client, settings):
    from core.models import LoginAttempt
    settings.REGISTRATION_SESSION_LIMIT = 2
    data = payload(client, email="not-an-email")
    assert client.post(URL, data).status_code == 200
    assert not StagedPerson.objects.exists()
    # Correcting a validation error uses the same token.
    data["email"] = "synthetic@example.com"
    assert client.post(URL, data).status_code == 302
    another = payload(client, first_name="Another")
    assert client.post(URL, another).status_code == 429
    LoginAttempt.objects.filter(key__startswith="reg:").update(
        window_started_at=timezone.now() - timedelta(hours=2)
    )
    assert client.post(URL, another).status_code == 302
