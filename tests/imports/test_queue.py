"""Review queue redesign (2026-08-21): "Can you make the reviewing of persons
not by batch but in a single location so i dont have to transfer between the
batches, add a filter for the batches." -- the volunteer's own request.

This covers imports/admin.py's queue_view (one merged, filterable list of
StagedPerson rows spanning every ImportBatch) and the way review_view now
threads a "reached from the queue" context through skip/reject/approve so the
reviewer returns to that same filtered, searched queue afterwards instead of
snapping back to whichever batch the row happened to live in. The per-batch
progress page (change_view) and the single-person review screen themselves
are unchanged and stay covered by tests/imports/test_search.py,
test_review.py and test_review_layout.py.

Two independent batches, created in this order so their uploaded_at values
are strictly increasing (ordinary object creation, no manual timestamps --
auto_now_add is enough since each INSERT happens on its own):

batch_a: tests/imports/fixtures/well_formed_import.json's usual three rows
(DELACRUZ JUAN MIGUEL / IMG_9001.jpg, DELACRUZ ROSARIO / IMG_9002.jpg,
MANGUBAT ELENA / IMG_9003.jpg).

batch_b: two fictional rows created directly (no real member data, per
CLAUDE.md/the task's own instruction) -- SANTOS, PEDRO (IMG_B001.jpg) and
REYES, MARIA (IMG_B002.jpg).
"""

from pathlib import Path
from urllib.parse import urlencode

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import groups
from imports.models import ImportBatch, StagedPerson, StagedPersonStatus
from imports.parsing import parse_import_json
from records.models import AccessLog

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec-queue", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def chairperson_user(db):
    user = User.objects.create_user("chair-queue", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    return user


@pytest.fixture
def two_batches(db):
    entries = parse_import_json((FIXTURES / "well_formed_import.json").read_bytes())
    batch_a = ImportBatch.objects.create(source_filename="well_formed_import.json")
    StagedPerson.objects.bulk_create(
        StagedPerson(batch=batch_a, sequence=i, raw_data=entry) for i, entry in enumerate(entries)
    )

    batch_b = ImportBatch.objects.create(source_filename="fictional_second_batch.json")
    StagedPerson.objects.bulk_create(
        [
            StagedPerson(
                batch=batch_b,
                sequence=0,
                raw_data={
                    "source_image": "IMG_B001.jpg",
                    "last_name": "SANTOS",
                    "first_name": "PEDRO",
                    "form_version": "v1",
                    "committees": [],
                },
            ),
            StagedPerson(
                batch=batch_b,
                sequence=1,
                raw_data={
                    "source_image": "IMG_B002.jpg",
                    "last_name": "REYES",
                    "first_name": "MARIA",
                    "form_version": "v1",
                    "committees": [],
                },
            ),
        ]
    )
    rows_by_name = {
        row.raw_data["last_name"] + row.raw_data["first_name"]: row
        for row in StagedPerson.objects.select_related("batch")
    }
    return batch_a, batch_b, rows_by_name


def _queue_url(**params):
    url = reverse("admin:imports_importbatch_queue")
    if params:
        url += "?" + urlencode(params)
    return url


def _review_url(batch, row):
    return reverse("admin:imports_importbatch_review", args=[batch.pk, row.pk])


# -- merged listing -----------------------------------------------------


@pytest.mark.django_db
def test_the_queue_shows_staged_people_from_two_different_batches_together(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    response = client.get(_queue_url())
    assert response.status_code == 200
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" in body
    assert "PEDRO SANTOS" in body
    assert "MARIA REYES" in body


@pytest.mark.django_db
def test_each_row_shows_which_batch_it_came_from(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    response = client.get(_queue_url())
    body = response.content.decode()
    assert str(batch_a) in body
    assert str(batch_b) in body


@pytest.mark.django_db
def test_rows_are_ordered_oldest_batch_first_then_upload_order_within_it(
    client, secretariat_user, two_batches
):
    """Ordering choice: (batch.uploaded_at, sequence) -- the batch that has
    been waiting longest goes first, and each batch's own paper-stack order
    (sequence) is preserved within it. batch_a was created before batch_b,
    so every batch_a name must appear, in sequence order, before every
    batch_b name."""
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url()).content.decode()
    positions = {
        name: body.index(name)
        for name in (
            "JUAN MIGUEL DELACRUZ",
            "ROSARIO DELACRUZ",
            "ELENA MANGUBAT",
            "PEDRO SANTOS",
            "MARIA REYES",
        )
    }
    assert positions["JUAN MIGUEL DELACRUZ"] < positions["ROSARIO DELACRUZ"] < positions["ELENA MANGUBAT"]
    assert positions["PEDRO SANTOS"] < positions["MARIA REYES"]
    assert positions["ELENA MANGUBAT"] < positions["PEDRO SANTOS"]


@pytest.mark.django_db
def test_no_bulk_approval_controls_appear_on_the_queue(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url()).content.decode()
    assert "select all" not in body.lower()
    assert "bulk" not in body.lower()
    assert 'type="checkbox"' not in body


# -- batch filter ---------------------------------------------------------


@pytest.mark.django_db
def test_the_batch_filter_narrows_to_one_batch(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    response = client.get(_queue_url(batch=batch_b.pk))
    assert response.status_code == 200
    body = response.content.decode()
    assert "PEDRO SANTOS" in body
    assert "MARIA REYES" in body
    assert "JUAN MIGUEL DELACRUZ" not in body
    assert "ROSARIO DELACRUZ" not in body
    assert "ELENA MANGUBAT" not in body


@pytest.mark.django_db
def test_clearing_the_batch_filter_restores_every_batch(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    narrowed = client.get(_queue_url(batch=batch_b.pk)).content.decode()
    assert "JUAN MIGUEL DELACRUZ" not in narrowed

    cleared = client.get(_queue_url()).content.decode()
    assert "JUAN MIGUEL DELACRUZ" in cleared
    assert "PEDRO SANTOS" in cleared


@pytest.mark.django_db
def test_the_batch_filter_scopes_the_counts_too(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url(batch=batch_b.pk)).content.decode()
    assert "Pending 2" in body
    assert "All 2" in body


# -- search across batches -------------------------------------------------


@pytest.mark.django_db
def test_search_finds_a_person_by_surname_across_batches(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url(q="SANTOS")).content.decode()
    assert "PEDRO SANTOS" in body
    assert "MARIA REYES" not in body
    assert "JUAN MIGUEL DELACRUZ" not in body


@pytest.mark.django_db
def test_search_finds_a_person_by_source_image_filename_across_batches(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url(q="B002")).content.decode()
    assert "MARIA REYES" in body
    assert "PEDRO SANTOS" not in body
    assert "ELENA MANGUBAT" not in body


@pytest.mark.django_db
def test_search_and_batch_filter_combine(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    body = client.get(_queue_url(q="DELACRUZ", batch=batch_a.pk)).content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "ROSARIO DELACRUZ" in body
    assert "ELENA MANGUBAT" not in body

    empty = client.get(_queue_url(q="DELACRUZ", batch=batch_b.pk)).content.decode()
    assert "JUAN MIGUEL DELACRUZ" not in empty
    assert "No entry matches" in empty


# -- status filter and counts ----------------------------------------------


@pytest.mark.django_db
def test_status_filter_narrows_the_list_and_carries_a_live_count(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    row = rows["DELACRUZJUAN MIGUEL"]
    row.status = StagedPersonStatus.APPROVED
    row.save()

    response = client.get(_queue_url(status="PENDING"))
    body = response.content.decode()
    assert "Pending 4" in body
    assert "JUAN MIGUEL DELACRUZ" not in body
    assert "ROSARIO DELACRUZ" in body
    assert "PEDRO SANTOS" in body


@pytest.mark.django_db
def test_counts_are_correct_across_batches(client, secretariat_user, two_batches):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    rows["DELACRUZJUAN MIGUEL"].status = StagedPersonStatus.APPROVED
    rows["DELACRUZJUAN MIGUEL"].save()
    rows["SANTOSPEDRO"].status = StagedPersonStatus.REJECTED
    rows["SANTOSPEDRO"].save()

    body = client.get(_queue_url()).content.decode()
    assert "All 5" in body
    assert "Pending 3" in body
    assert "Approved 1" in body
    assert "Rejected 1" in body


# -- approve/reject from the queue returns to it ----------------------------


def _approve_post_data(row, queue_ctx=None):
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
        "committees": data.get("committees") or [],
        "membership_status": "MEMBER",
        "children-TOTAL_FORMS": str(len(data.get("children") or [])),
        "children-INITIAL_FORMS": str(len(data.get("children") or [])),
        "children-MIN_NUM_FORMS": "0",
        "children-MAX_NUM_FORMS": "1000",
    }
    for index, child in enumerate(data.get("children") or []):
        post[f"children-{index}-full_name"] = child["full_name"]
        post[f"children-{index}-date_of_birth"] = child.get("date_of_birth") or ""
    if queue_ctx is not None:
        post["queue_return"] = "1"
        post["queue_q"] = queue_ctx.get("q", "")
        post["queue_status"] = queue_ctx.get("status", "")
        post["queue_batch"] = queue_ctx.get("batch", "")
    return post


@pytest.mark.django_db
def test_a_review_link_from_the_queue_carries_the_filters_and_shows_a_queue_back_link(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    # Exactly the link the queue template renders for a pending row.
    row = rows["SANTOSPEDRO"]
    url = (
        _review_url(batch_b, row)
        + "?queue_return=1&queue_q=SANTOS&queue_status=&queue_batch="
        + str(batch_b.pk)
    )
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert "Back to review queue" in body
    assert f'name="queue_batch" value="{batch_b.pk}"' in body
    assert 'name="queue_q" value="SANTOS"' in body


@pytest.mark.django_db
def test_approving_from_the_queue_advances_to_the_next_matching_row_keeping_filters(
    client, secretariat_user, two_batches
):
    """Two pending rows both match batch_filter=batch_a with no search or
    status filter. Approving the first must land the reviewer directly on
    the second one's review screen, still carrying the same queue filters --
    "continuous queue," not a trip back to a list after every single
    decision."""
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    queue_ctx = {"q": "", "status": "", "batch": str(batch_a.pk)}
    first = rows["DELACRUZJUAN MIGUEL"]  # sequence 0 in batch_a
    post = _approve_post_data(first, queue_ctx)
    response = client.post(_review_url(batch_a, first), post)
    assert response.status_code == 302

    second = rows["DELACRUZROSARIO"]
    expected = _review_url(batch_a, second)
    assert response.url.startswith(expected)
    assert "queue_return=1" in response.url
    assert f"queue_batch={batch_a.pk}" in response.url


@pytest.mark.django_db
def test_approving_the_last_matching_row_returns_to_the_queue_list_with_filters_intact(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    queue_ctx = {"q": "REYES", "status": "", "batch": ""}
    row = rows["REYESMARIA"]
    post = _approve_post_data(row, queue_ctx)
    response = client.post(_review_url(batch_b, row), post)
    assert response.status_code == 302
    assert response.url == _queue_url(q="REYES")

    # Landing there shows the now-approved person under the Approved tab,
    # and nothing pending still matches "REYES".
    landed = client.get(response.url)
    assert landed.status_code == 200
    body = landed.content.decode()
    assert "MARIA REYES" in body


@pytest.mark.django_db
def test_rejecting_from_the_queue_also_returns_to_it_with_filters_intact(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    queue_ctx = {"q": "", "status": "", "batch": str(batch_b.pk)}
    santos = rows["SANTOSPEDRO"]
    reject_post = {
        "action": "reject",
        "queue_return": "1",
        "queue_q": "",
        "queue_status": "",
        "queue_batch": str(batch_b.pk),
    }
    response = client.post(_review_url(batch_b, santos), reject_post)
    assert response.status_code == 302

    # One pending row (Reyes) still matches batch_b -- advance goes straight
    # to it, still tagged with the same queue filters.
    reyes = rows["REYESMARIA"]
    assert response.url.startswith(_review_url(batch_b, reyes))
    assert f"queue_batch={batch_b.pk}" in response.url

    final = client.post(
        _review_url(batch_b, reyes),
        {**reject_post, "action": "reject"},
    )
    assert final.status_code == 302
    assert final.url == _queue_url(batch=batch_b.pk)


@pytest.mark.django_db
def test_skipping_from_the_queue_moves_to_the_next_matching_pending_row(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    santos = rows["SANTOSPEDRO"]
    response = client.post(
        _review_url(batch_b, santos),
        {"action": "skip", "queue_return": "1", "queue_q": "", "queue_status": "", "queue_batch": ""},
    )
    assert response.status_code == 302
    reyes = rows["REYESMARIA"]
    assert response.url.startswith(_review_url(batch_b, reyes))
    santos.refresh_from_db()
    assert santos.status == StagedPersonStatus.PENDING


@pytest.mark.django_db
def test_approving_from_a_batch_progress_page_keeps_the_old_per_batch_behaviour(
    client, secretariat_user, two_batches
):
    """No queue_return marker at all (the existing per-batch route) must
    behave exactly as before: straight to the next pending row in that same
    batch, never redirected into the queue."""
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    first = rows["DELACRUZJUAN MIGUEL"]
    response = client.post(_review_url(batch_a, first), _approve_post_data(first))
    assert response.status_code == 302
    second = rows["DELACRUZROSARIO"]
    assert response.url == _review_url(batch_a, second)


# -- the per-batch view keeps working ----------------------------------------


@pytest.mark.django_db
def test_the_per_batch_progress_page_still_works_unaffected_by_the_queue(
    client, secretariat_user, two_batches
):
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    response = client.get(reverse("admin:imports_importbatch_change", args=[batch_a.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "JUAN MIGUEL DELACRUZ" in body
    assert "PEDRO SANTOS" not in body  # scoped to this batch only


# -- viewing the queue does not itself write an AccessLog --------------------


@pytest.mark.django_db
def test_viewing_the_queue_list_writes_no_access_log_entry(client, secretariat_user, two_batches):
    """Decision: the queue list shows exactly the same fields the per-batch
    progress list already shows without logging -- name, source image,
    status, and now which batch -- never the full profile (DOB, address,
    phone, email, children, emergency contact) that earns a log entry on the
    single-person review screen (see review_view's own AccessLog.record
    call, IMPORTANT 3). Browsing the merged list is not viewing anyone's
    full record, so it stays consistent with the progress page and does not
    log on its own.
    """
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    assert AccessLog.objects.count() == 0
    response = client.get(_queue_url())
    assert response.status_code == 200
    assert AccessLog.objects.count() == 0


@pytest.mark.django_db
def test_viewing_one_row_from_the_queue_still_writes_the_usual_access_log_entry(
    client, secretariat_user, two_batches
):
    """The single-person screen's existing log write (IMPORTANT 3) is
    unchanged by being reached through the queue instead of a batch."""
    batch_a, batch_b, rows = two_batches
    client.force_login(secretariat_user)

    row = rows["SANTOSPEDRO"]
    url = _review_url(batch_b, row) + "?queue_return=1&queue_q=&queue_status=&queue_batch="
    response = client.get(url)
    assert response.status_code == 200

    entry = AccessLog.objects.get()
    assert entry.user == secretariat_user
    assert entry.person is None
    assert "SANTOS" in entry.report.upper()


# -- access control -----------------------------------------------------


@pytest.mark.django_db
def test_a_chairperson_only_user_gets_403_on_the_queue(client, chairperson_user, two_batches):
    client.force_login(chairperson_user)
    response = client.get(_queue_url())
    assert response.status_code == 403


@pytest.mark.django_db
def test_an_anonymous_user_is_redirected_to_login(client, two_batches):
    response = client.get(_queue_url())
    assert response.status_code == 302
    assert "login" in response.url
