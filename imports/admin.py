import hashlib
import re
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from unfold.admin import ModelAdmin

from core.groups import is_chairperson_only
from records.models import AccessLog

from .forms import ChildFormSet, StagedPersonForm, UploadForm, children_initial, initial_from_data
from .models import ImportBatch, StagedPerson, StagedPersonStatus, status_counts
from .parsing import ImportValidationError
from .services import build_person_from_import, committee_cap_warning, possible_duplicate_warning
from .spreadsheet import parse_import_file, write_blank_template_bytes


def _next_pending_row(batch, after_sequence=None):
    pending = batch.rows.filter(status=StagedPersonStatus.PENDING)
    if after_sequence is not None:
        after = pending.filter(sequence__gt=after_sequence).order_by("sequence").first()
        if after is not None:
            return after
    return pending.order_by("sequence").first()


# -- row search (batch list) ---------------------------------------------
# A volunteer holds one paper sheet and needs to land on its screen entry in
# seconds, not scroll a list in upload order (docs/IMPORT_TEMPLATE.md's
# entries are exactly the order the AI happened to process photos in, which
# is not the order of the physical pile). Matching is deliberately forgiving
# -- case-insensitive, partial, and blind to the punctuation people do not
# type -- so "delacruz", "Dela Cruz" and "DELA-CRUZ" all find the same row,
# and someone comparing against a photo filename can type just the digits.
_SEARCH_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _normalize_search_text(value) -> str:
    return _SEARCH_STRIP_RE.sub("", str(value or "").lower())


def _row_matches_search(row, normalized_query: str) -> bool:
    data = row.effective_data
    first = data.get("first_name") or ""
    last = data.get("last_name") or ""
    haystacks = (last, first, f"{first} {last}", data.get("source_image") or "")
    return any(normalized_query in _normalize_search_text(text) for text in haystacks if text)


# -- review queue (across every batch) -------------------------------------
# "make the reviewing of persons not by batch but in a single location so i
# dont have to transfer between the batches, add a filter for the batches"
# -- the volunteer's own request. Batches are an artefact of how files were
# uploaded, not of how the work is done; this section builds one merged,
# filterable queue on top of the same StagedPerson rows the per-batch screens
# already use, without changing how a single row is decided (still
# review_view, unchanged in that respect).
#
# Ordering: (batch__uploaded_at, batch_id, sequence) -- oldest batch first,
# each batch's own rows in their original upload order. Two reasons, not one:
# a batch is itself one physical stack of paper (docs/IMPORT_TEMPLATE.md),
# so keeping sequence as the tiebreak preserves whatever coherence that pile
# already had, exactly as the single-batch screens do today; and ordering
# batches oldest-first means the entries that have been waiting longest are
# always reviewed first, so a growing backlog of new uploads can never
# strand an older batch half-finished. Confidence was considered and
# rejected: it optimises the reviewer's moment-to-moment effort but has
# nothing to do with fairness across batches, and every field on this screen
# stays editable regardless of confidence (review.html), so it is not a
# signal this queue's ordering should chase. `batch_id` only breaks ties on
# `uploaded_at` (auto_now_add, but not guaranteed unique to the microsecond)
# -- it does not carry meaning on its own.
_QUEUE_ORDER = ("batch__uploaded_at", "batch_id", "sequence")


def _clean_batch_filter(raw) -> str:
    raw = (raw or "").strip()
    return raw if raw.isdigit() else ""


def _clean_status_filter(raw) -> str:
    raw = (raw or "").strip().upper()
    return raw if raw in StagedPersonStatus.values else ""


def _filtered_queue_rows(*, batch_id_filter="", status_filter="", query=""):
    """Every StagedPerson matching the queue's batch/status/search filters,
    in `_QUEUE_ORDER`. Search is applied in Python, same as the per-batch
    list (_row_matches_search) and for the same reason: the searched fields
    live inside a JSONField, and a realistic backlog -- a handful of batches
    of tens of forms each -- is nowhere near large enough to need it done in
    the database.
    """
    rows = StagedPerson.objects.select_related("batch", "created_person")
    if batch_id_filter:
        rows = rows.filter(batch_id=batch_id_filter)
    if status_filter:
        rows = rows.filter(status=status_filter)
    rows = rows.order_by(*_QUEUE_ORDER)
    if query:
        normalized_query = _normalize_search_text(query)
        return [row for row in rows if _row_matches_search(row, normalized_query)]
    return list(rows)


def _pending_queue_candidates(batch_id_filter, query):
    return _filtered_queue_rows(
        batch_id_filter=batch_id_filter, status_filter=StagedPersonStatus.PENDING, query=query
    )


def _next_pending_in_queue(current_batch, current_row, batch_id_filter, query):
    """The next pending row after `current_row`, within the same filtered,
    ordered set _pending_queue_candidates builds -- the queue equivalent of
    _next_pending_row above."""
    key = (current_batch.uploaded_at, current_batch.pk, current_row.sequence)
    for row in _pending_queue_candidates(batch_id_filter, query):
        if (row.batch.uploaded_at, row.batch_id, row.sequence) > key:
            return row
    return None


def _queue_return_context(request):
    """None unless this request carries the queue_return=1 marker a link or
    hidden field from the queue put there -- see queue.html and review.html.
    Reachable both on GET (a link from the queue's own rows) and POST (the
    hidden fields carried through the review form's submit), so it reads
    whichever of the two actually has the data.
    """
    source = request.POST if request.method == "POST" else request.GET
    if source.get("queue_return") != "1":
        return None
    return {
        "q": source.get("queue_q") or "",
        "status": _clean_status_filter(source.get("queue_status")),
        "batch": _clean_batch_filter(source.get("queue_batch")),
    }


def _review_url_with_queue(batch_id, row_id, queue_ctx):
    url = reverse("admin:imports_importbatch_review", args=[batch_id, row_id])
    params = {"queue_return": "1"}
    if queue_ctx["q"]:
        params["queue_q"] = queue_ctx["q"]
    if queue_ctx["status"]:
        params["queue_status"] = queue_ctx["status"]
    if queue_ctx["batch"]:
        params["queue_batch"] = queue_ctx["batch"]
    return f"{url}?{urlencode(params)}"


def _queue_list_url(queue_ctx):
    url = reverse("admin:imports_importbatch_queue")
    params = {k: v for k, v in queue_ctx.items() if v}
    return f"{url}?{urlencode(params)}" if params else url


@admin.register(ImportBatch)
class ImportBatchAdmin(ModelAdmin):
    """This is Secretariat and ICT work (docs/IMPORT_TEMPLATE.md): a
    Committee Chairperson holds no permission on this app at all (see
    imports/migrations/0002_grant_group_permissions.py), and every entry
    point below re-checks is_chairperson_only besides, the same
    belt-and-suspenders pattern people.admin.PersonAdmin and
    committees.admin.CommitteeMembershipAdmin already use.
    """

    list_display = ("__str__", "uploaded_by", "uploaded_at", "pending_count", "approved_count", "rejected_count")
    ordering = ("-uploaded_at",)

    # -- access control -----------------------------------------------

    def has_module_permission(self, request):
        if is_chairperson_only(request.user):
            return False
        return super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        if is_chairperson_only(request.user):
            return False
        return super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        if is_chairperson_only(request.user):
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if is_chairperson_only(request.user):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if is_chairperson_only(request.user):
            return False
        return super().has_delete_permission(request, obj)

    def _require_reviewer(self, request, perm):
        """Every custom view below bypasses Django's own dispatch-time
        permission checks (those only run for add_view/change_view/etc.),
        so each one calls this first. Denies chairperson-only users
        outright, then falls back to the ordinary Django permission.
        """
        if is_chairperson_only(request.user) or not request.user.has_perm(perm):
            raise PermissionDenied

    def _stay(self, batch, row, queue_ctx):
        """Redirect back to this same row -- used when a race (someone else
        decided it first, see CRITICAL 2) means there is nothing new to
        advance to. Keeps the queue's filters attached if that is where the
        reviewer came from, so the "back to queue" link stays correct.
        """
        if queue_ctx is not None:
            return redirect(_review_url_with_queue(batch.pk, row.pk, queue_ctx))
        return redirect("admin:imports_importbatch_review", batch.pk, row.pk)

    def _advance(self, batch, row, queue_ctx):
        """Where the reviewer lands after skip/reject/approve. Outside the
        queue this is unchanged: jump straight to the next pending row in
        this batch, or the batch's own progress page once none remain
        (_next_pending_row). From the queue, "next" and "nothing left" both
        stay inside that same filtered, searched queue instead -- see
        _next_pending_in_queue and _queue_list_url -- so approving one entry
        keeps the volunteer moving through the queue they were working
        without an extra page load, and only lands on the queue's own list
        once that filtered set is actually exhausted.
        """
        if queue_ctx is not None:
            next_row = _next_pending_in_queue(batch, row, queue_ctx["batch"], queue_ctx["q"])
            if next_row is not None:
                return redirect(_review_url_with_queue(next_row.batch_id, next_row.pk, queue_ctx))
            return redirect(_queue_list_url(queue_ctx))
        target = _next_pending_row(batch, after_sequence=row.sequence)
        if target:
            return redirect("admin:imports_importbatch_review", batch.pk, target.pk)
        return redirect("admin:imports_importbatch_change", batch.pk)

    # -- list display ---------------------------------------------------

    @admin.display(description="Pending")
    def pending_count(self, obj):
        return obj.counts()["pending"]

    @admin.display(description="Approved")
    def approved_count(self, obj):
        return obj.counts()["approved"]

    @admin.display(description="Rejected")
    def rejected_count(self, obj):
        return obj.counts()["rejected"]

    # -- urls -------------------------------------------------------------

    def get_urls(self):
        custom = [
            path(
                "upload/",
                self.admin_site.admin_view(self.upload_view),
                name="imports_importbatch_upload",
            ),
            path(
                "template/",
                self.admin_site.admin_view(self.download_template_view),
                name="imports_importbatch_download_template",
            ),
            path(
                "queue/",
                self.admin_site.admin_view(self.queue_view),
                name="imports_importbatch_queue",
            ),
            path(
                "<int:batch_id>/review/<int:row_id>/",
                self.admin_site.admin_view(self.review_view),
                name="imports_importbatch_review",
            ),
        ]
        return custom + super().get_urls()

    def add_view(self, request, form_url="", extra_context=None):
        # "Add" on a staging batch means "upload a file", not "fill in a
        # blank form" -- reuse Unfold's own "+ Add" button/permission
        # instead of building a second entry point.
        return redirect(reverse("admin:imports_importbatch_upload"))

    # -- blank template download -----------------------------------------

    def download_template_view(self, request):
        # Same permission as uploading -- this is part of the upload flow,
        # not a separate capability, and a chairperson has neither.
        self._require_reviewer(request, "imports.add_importbatch")
        response = HttpResponse(
            write_blank_template_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            'attachment; filename="member_profiling_import_template.xlsx"'
        )
        return response

    # -- upload -------------------------------------------------------------

    def upload_view(self, request):
        self._require_reviewer(request, "imports.add_importbatch")
        errors: list[str] = None
        if request.method == "POST":
            form = UploadForm(request.POST, request.FILES)
            if form.is_valid():
                raw = form.cleaned_data["file"].read()
                try:
                    entries = parse_import_file(raw)
                except ImportValidationError as exc:
                    errors = exc.errors
                else:
                    # IMPORTANT 7 (2026-08-16 import fixes): nothing used to
                    # notice the same file being uploaded twice -- an
                    # accidental double-click, or someone re-running the same
                    # export, silently staged a second batch of the same
                    # people. A content hash is the simplest reliable "is
                    # this the same file" check (the filename alone changes
                    # too easily to trust). This warns, it never blocks -- a
                    # genuine corrected re-upload of the same filename is
                    # legitimate and must still stage.
                    content_hash = hashlib.sha256(raw).hexdigest()
                    duplicate_batch = (
                        ImportBatch.objects.filter(content_hash=content_hash)
                        .order_by("-uploaded_at")
                        .first()
                    )
                    # A Google Forms response sheet is a RUNNING list: the
                    # volunteer re-uploads the same file with a few more rows
                    # each time (docs/ONLINE_FORM.md). Every entry carries the
                    # submission timestamp, which never changes as the sheet
                    # grows, so anything already staged in ANY earlier batch is
                    # skipped here -- whatever became of it. A row that was
                    # approved must not come back, and neither must one that
                    # was rejected or is still sitting in the queue.
                    already_staged = set(
                        StagedPerson.objects.exclude(source_key="").values_list(
                            "source_key", flat=True
                        )
                    )
                    fresh, repeats = [], 0
                    for entry in entries:
                        source_key = entry.pop("_source_key", "")
                        if source_key and source_key in already_staged:
                            repeats += 1
                            continue
                        if source_key:
                            already_staged.add(source_key)
                        fresh.append((source_key, entry))

                    if not fresh:
                        self.message_user(
                            request,
                            f"Every one of the {repeats} response(s) in that file has "
                            "already been imported. Nothing new to review.",
                            messages.INFO,
                        )
                        return redirect("admin:imports_importbatch_queue")

                    batch = ImportBatch.objects.create(
                        source_filename=form.cleaned_data["file"].name,
                        uploaded_by=request.user,
                        content_hash=content_hash,
                    )
                    StagedPerson.objects.bulk_create(
                        StagedPerson(
                            batch=batch,
                            sequence=index,
                            raw_data=entry,
                            source_key=source_key,
                        )
                        for index, (source_key, entry) in enumerate(fresh)
                    )
                    if repeats:
                        self.message_user(
                            request,
                            f"{len(fresh)} new response(s) staged. {repeats} were "
                            "already imported and were skipped.",
                            messages.INFO,
                        )
                    if duplicate_batch is not None:
                        self.message_user(
                            request,
                            f"This file's content matches a previous import, {duplicate_batch} "
                            f"(uploaded by {duplicate_batch.uploaded_by or 'a user no longer on file'}). "
                            "Staged anyway in case this is a genuine corrected re-upload -- "
                            "check it is not an accidental repeat before reviewing.",
                            messages.WARNING,
                        )
                    self.message_user(
                        request, f"Staged {len(entries)} people for review.", messages.SUCCESS
                    )
                    return redirect("admin:imports_importbatch_change", batch.pk)
        else:
            form = UploadForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Upload member profiling import",
            "opts": self.model._meta,
            "form": form,
            "errors": errors,
        }
        return render(request, "admin/imports/importbatch/upload.html", context)

    # -- review queue (every batch, one place) ---------------------------

    def queue_view(self, request):
        # Same permission as the per-batch progress page -- this is the same
        # capability (see the rows still pending across every batch), merely
        # not scoped to one of them.
        self._require_reviewer(request, "imports.view_importbatch")

        batch_filter = _clean_batch_filter(request.GET.get("batch"))
        status_filter = _clean_status_filter(request.GET.get("status"))
        query = (request.GET.get("q") or "").strip()

        rows = _filtered_queue_rows(
            batch_id_filter=batch_filter, status_filter=status_filter, query=query
        )

        # Counts (and the "Continue reviewing" target below) follow the batch
        # filter but deliberately ignore the search box and the status tabs
        # themselves -- exactly like the per-batch progress page's counts
        # (ImportBatch.counts()) already ignore its own search box, so "how
        # many remain" always means the true total, not "how many match what
        # I just typed."
        counts_qs = StagedPerson.objects.all()
        if batch_filter:
            counts_qs = counts_qs.filter(batch_id=batch_filter)
        counts = status_counts(counts_qs)

        pending_candidates = _pending_queue_candidates(batch_filter, query)
        next_row = pending_candidates[0] if pending_candidates else None
        queue_ctx = {"q": query, "status": status_filter, "batch": batch_filter}

        context = {
            **self.admin_site.each_context(request),
            "title": "Review queue",
            "opts": self.model._meta,
            "rows": rows,
            "counts": counts,
            "batches": ImportBatch.objects.order_by("-uploaded_at"),
            "batch_filter": batch_filter,
            "status_filter": status_filter,
            "query": query,
            "next_row": next_row,
            "next_row_url": (
                _review_url_with_queue(next_row.batch_id, next_row.pk, queue_ctx)
                if next_row
                else ""
            ),
            "queue_ctx": queue_ctx,
        }
        return render(request, "admin/imports/importbatch/queue.html", context)

    # -- progress / batch detail ---------------------------------------

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self._require_reviewer(request, "imports.view_importbatch")
        batch = get_object_or_404(ImportBatch, pk=object_id)
        rows = batch.rows.select_related("created_person").order_by("sequence")

        # "a way to see, at a glance, which rows are still pending" -- a
        # status filter with a live count in each tab's own label, rather
        # than making the reviewer count status badges down the table.
        status_filter = (request.GET.get("status") or "").strip().upper()
        if status_filter in StagedPersonStatus.values:
            rows = rows.filter(status=status_filter)

        # "so i can easily find the imported form of the paper im looking
        # at" -- the whole point of this search box. See _row_matches_search.
        # Done in Python, not the ORM, because the fields searched live
        # inside a JSONField (raw_data/edited_data) and a realistic batch is
        # tens of rows, not thousands (imports/forms.py's own MAX_IMPORT_FILE
        # cap assumes the same).
        query = (request.GET.get("q") or "").strip()
        if query:
            normalized_query = _normalize_search_text(query)
            rows = [row for row in rows if _row_matches_search(row, normalized_query)]

        next_row = batch.next_pending()
        context = {
            **self.admin_site.each_context(request),
            "title": str(batch),
            "opts": self.model._meta,
            "original": batch,
            "batch": batch,
            "rows": rows,
            "counts": batch.counts(),
            "next_row": next_row,
            "query": query,
            "status_filter": status_filter,
        }
        return render(request, "admin/imports/importbatch/progress.html", context)

    # -- per-person review --------------------------------------------

    def review_view(self, request, batch_id, row_id):
        self._require_reviewer(request, "imports.change_stagedperson")
        batch = get_object_or_404(ImportBatch, pk=batch_id)
        row = get_object_or_404(StagedPerson, pk=row_id, batch=batch)

        # None when this row was reached from a batch's own progress page
        # (today's route, unchanged below); a dict of the queue's active
        # batch/status/search filters when it was reached from the merged
        # review queue instead (queue.html's rows, and its "Continue
        # reviewing" button, all link in carrying queue_return=1 -- see
        # _queue_return_context). Read once here and threaded through both
        # the template (for the hidden fields and back-link, see
        # review.html) and every redirect below, so a decision made from the
        # queue always returns to that same filtered, searched queue instead
        # of snapping back to this one batch.
        queue_ctx = _queue_return_context(request)

        # IMPORTANT 3 (2026-08-16 import fixes): every Person view in this
        # system writes an AccessLog row (people/admin.py's PersonAdmin --
        # the RA 10173 "who looked at whom" trail); this screen renders the
        # same class of data -- name, birthdate, address, phone, email,
        # children, emergency contact -- and never logged anything, for
        # pending, approved or rejected rows alike. AccessLog.record requires
        # exactly one of `person`/`report`. A still-pending or rejected row
        # has no Person to point at, so it logs against `report`, a stable
        # label identifying the staged row. Once a row is approved, viewing
        # it again *is* viewing that Person's own data under a different
        # URL, so from then on it logs against the real `person` instead --
        # consistent with every other view of that same Person, and the
        # access now shows up in that person's own history, not a label
        # nobody could otherwise search for.
        if row.created_person_id:
            AccessLog.record(
                user=request.user, person=row.created_person, ip=request.META.get("REMOTE_ADDR")
            )
        else:
            AccessLog.record(
                user=request.user,
                report=f"import review: {row}"[:120],
                ip=request.META.get("REMOTE_ADDR"),
            )

        read_only = row.status != StagedPersonStatus.PENDING

        if request.method == "POST" and not read_only:
            action = request.POST.get("action")

            if action == "skip":
                return self._advance(batch, row, queue_ctx)

            if action == "reject":
                # Same overlapping-request protection as "approve" below --
                # cheaper to consider here too than to special-case it out.
                with transaction.atomic():
                    row = StagedPerson.objects.select_for_update().get(pk=row.pk)
                    if row.status != StagedPersonStatus.PENDING:
                        self.message_user(
                            request,
                            f"{row} was already decided by someone else in the meantime -- "
                            "nothing was changed.",
                            messages.WARNING,
                        )
                        return self._stay(batch, row, queue_ctx)
                    row.status = StagedPersonStatus.REJECTED
                    row.error_message = ""
                    row.reviewed_by = request.user
                    row.reviewed_at = timezone.now()
                    row.save()
                self.message_user(request, f"Rejected {row}.", messages.WARNING)
                return self._advance(batch, row, queue_ctx)

            if action == "approve":
                form = StagedPersonForm(request.POST)
                formset = ChildFormSet(request.POST, prefix="children")
                if form.is_valid() and formset.is_valid():
                    cleaned = dict(form.cleaned_data)
                    children = [c for c in formset.cleaned_data if c.get("full_name")]
                    approved_person = None
                    notices: list[str] = []

                    # CRITICAL 2 (2026-08-16 import fixes): `row` above was
                    # fetched with a plain, unlocked read. Two overlapping
                    # approvals of the same row -- two tabs, or a slow
                    # request plus a back-button resubmit -- both used to see
                    # PENDING and both build a complete Person before either
                    # wrote `status` back, leaving an untraceable duplicate
                    # in the register. SELECT ... FOR UPDATE inside this
                    # atomic block makes the second request wait for the
                    # first to finish committing, then re-reads `status` --
                    # by then APPROVED -- and refuses instead of silently
                    # building a second person. This nests inside
                    # build_person_from_import's own atomic() as a savepoint
                    # rather than a second real transaction, so that
                    # function's own all-or-nothing guarantee is untouched.
                    with transaction.atomic():
                        row = StagedPerson.objects.select_for_update().get(pk=row.pk)
                        if row.status != StagedPersonStatus.PENDING:
                            self.message_user(
                                request,
                                f"{row} was already decided by someone else in the meantime -- "
                                "nothing was created.",
                                messages.WARNING,
                            )
                            return self._stay(batch, row, queue_ctx)

                        row.edited_data = {**row.effective_data, **cleaned}
                        row.edited_data["children"] = children
                        try:
                            approved_person, notices = build_person_from_import(
                                cleaned, children, request.user
                            )
                        except ValidationError as exc:
                            row.error_message = "; ".join(exc.messages)
                            row.save()
                            approved_person = None
                        else:
                            row.status = StagedPersonStatus.APPROVED
                            row.error_message = ""
                            row.created_person = approved_person
                            row.reviewed_by = request.user
                            row.reviewed_at = timezone.now()
                            row.save()

                    if approved_person is not None:
                        for notice in notices:
                            self.message_user(request, notice, messages.INFO)
                        self.message_user(
                            request, f"Approved {approved_person.full_name}.", messages.SUCCESS
                        )
                        return self._advance(batch, row, queue_ctx)
                    else:
                        self.message_user(
                            request,
                            f"Could not approve {row}: {row.error_message}",
                            messages.ERROR,
                        )
            else:
                form = None
                formset = None
        else:
            form = None
            formset = None

        if form is None:
            data = row.effective_data
            form = StagedPersonForm(initial=initial_from_data(data))
            formset = ChildFormSet(initial=children_initial(data), prefix="children")

        # MINOR 8 (2026-08-16 import fixes): this used to only fire *after*
        # the Person already existed, as a flash message on the way out of a
        # successful approval -- useless for catching a wrong match, since
        # by then it was too late to do anything but merge by hand. Computed
        # here, from the row's own field values, it shows on the review
        # screen itself, before the reviewer decides.
        duplicate_warning = None
        committee_warning = None
        if not read_only:
            duplicate_warning = possible_duplicate_warning(row.effective_data)
            # Same reasoning, same timing -- see committee_cap_warning's
            # docstring for why this no longer refuses at approval.
            committee_warning = committee_cap_warning(row.effective_data)

        # Field-level flags, moved onto the fields themselves (see
        # review.html / _field.html) instead of a separate block the
        # reviewer had to read and then mentally map back onto the form.
        # Keyed by the AI's own field name so each include can look itself
        # up directly, e.g. uncertain_by_field.date_of_birth.
        uncertain_by_field = {}
        for item in row.raw_data.get("uncertain_fields") or []:
            if isinstance(item, dict) and item.get("field"):
                uncertain_by_field[item["field"]] = item

        # A flag naming something this screen has no single field for --
        # "children" as a whole, or a name the AI wrote that does not match
        # any field this form renders -- must not silently vanish just
        # because there is no one field to pin it to. "children" itself is
        # handled at the Children section heading in review.html; anything
        # else is listed in `other_flags` as a last resort.
        known_field_names = set(StagedPersonForm.base_fields) | {"children"}
        other_flags = [
            item for name, item in uncertain_by_field.items() if name not in known_field_names
        ]

        counts = batch.counts()
        decided = counts["approved"] + counts["rejected"]
        progress_percent = round(decided / counts["total"] * 100) if counts["total"] else 0

        context = {
            **self.admin_site.each_context(request),
            "title": f"Review {row}",
            "opts": self.model._meta,
            "batch": batch,
            "row": row,
            "effective_data": row.effective_data,
            "uncertain_by_field": uncertain_by_field,
            "other_flags": other_flags,
            "confidence": row.raw_data.get("confidence"),
            "duplicate_warning": duplicate_warning,
            "committee_warning": committee_warning,
            "form": form,
            "formset": formset,
            "read_only": read_only,
            "counts": counts,
            "progress_percent": progress_percent,
            "queue_return": queue_ctx,
        }
        return render(request, "admin/imports/importbatch/review.html", context)
