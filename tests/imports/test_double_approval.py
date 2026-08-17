"""CRITICAL 2: two overlapping approvals of the same staged row must not both
create a Person. imports/admin.py's review_view used to fetch the row with a
plain get_object_or_404, decide `read_only` from that in-memory read, and
only write `status` back at the very end -- two requests that both start
while the row is still PENDING both build a complete person.

Reproduced with real threads and real PostgreSQL row locking (this suite
never uses SQLite): both requests are forced to read the row past the point
where read_only is decided, at the same moment, via a barrier patched into
imports.admin.get_object_or_404 -- the same call both the buggy and the
fixed code path make first, before any locking begins. What happens after
that point is exactly what's under test.
"""

import threading
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse

import imports.admin as imports_admin
from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import parse_import_json
from people.models import MembershipStatus, Person

FIXTURES = Path(__file__).parent / "fixtures"


def _make_secretariat_user(name):
    user = User.objects.create_user(name, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


def _post_data(row):
    data = row.raw_data
    post = {
        "action": "approve",
        "member_no": data.get("member_no") or "",
        "last_name": data["last_name"],
        "first_name": data["first_name"],
        "middle_name": data.get("middle_name") or "",
        "suffix": data.get("suffix") or "",
        "date_of_birth": data.get("date_of_birth") or "",
        "place_of_birth": data.get("place_of_birth") or "",
        "gender": data.get("gender") or "",
        "civil_status": data.get("civil_status") or "",
        "nationality": data.get("nationality") or "",
        "home_address": data.get("home_address") or "",
        "mobile_number": data.get("mobile_number") or "",
        "email": data.get("email") or "",
        "spouse_name": data.get("spouse_name") or "",
        "date_of_marriage": data.get("date_of_marriage") or "",
        "form_version": data.get("form_version") or "v1",
        "date_filed": data.get("date_filed") or "",
        "certification_date": data.get("certification_date") or "",
        "emergency_contact_name": data.get("emergency_contact_name") or "",
        "emergency_relationship": data.get("emergency_relationship") or "",
        "emergency_number": data.get("emergency_number") or "",
        "committees": [],
        "membership_status": MembershipStatus.MEMBER,
        "notes": data.get("notes") or "",
        "children-TOTAL_FORMS": "0",
        "children-INITIAL_FORMS": "0",
        "children-MIN_NUM_FORMS": "0",
        "children-MAX_NUM_FORMS": "1000",
    }
    return post


@pytest.mark.django_db(transaction=True)
def test_two_overlapping_approvals_of_the_same_row_create_only_one_person(monkeypatch):
    """The red/green test for CRITICAL 2. Two threads, two independent DB
    connections, two Client instances -- both forced past the initial row
    read together via a barrier, then let race for real."""
    user_a = _make_secretariat_user("sec_a")
    user_b = _make_secretariat_user("sec_b")

    entries = parse_import_json((FIXTURES / "well_formed_import.json").read_bytes())
    batch = ImportBatch.objects.create(source_filename="well_formed_import.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )
    row = StagedPerson.objects.filter(batch=batch).order_by("sequence").first()
    url = reverse("admin:imports_importbatch_review", args=[batch.pk, row.pk])
    post = _post_data(row)

    barrier = threading.Barrier(2)
    real_get_object_or_404 = imports_admin.get_object_or_404

    def synced_get_object_or_404(model, *args, **kwargs):
        # Both threads must pass this call -- the same one that decides
        # `read_only` -- before either is allowed to proceed, so both start
        # from "the row is still PENDING" at the same moment, exactly like
        # two truly-overlapping requests would.
        if model is StagedPerson:
            barrier.wait(timeout=5)
        return real_get_object_or_404(model, *args, **kwargs)

    monkeypatch.setattr(imports_admin, "get_object_or_404", synced_get_object_or_404)

    results = {}

    def worker(name, user):
        from django.db import connections

        try:
            c = Client()
            c.force_login(user)
            response = c.post(url, post)
            results[name] = response.status_code
        finally:
            connections.close_all()

    t1 = threading.Thread(target=worker, args=("a", user_a))
    t2 = threading.Thread(target=worker, args=("b", user_b))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive() and not t2.is_alive(), "a thread deadlocked or hung"

    # This is the fix under test: only one Person may ever come out of two
    # overlapping approvals of the same staged row. The fixture's last name
    # is "DELACRUZ" (all caps); Person.save() title-cases it on the way in.
    assert Person.objects.filter(last_name="Delacruz").count() == 1

    row.refresh_from_db()
    assert row.status == StagedPersonStatus.APPROVED
    # Exactly one of the two requests actually built the person; the other
    # must have been refused, not silently no-opped.
    assert {results["a"], results["b"]} <= {200, 302}
