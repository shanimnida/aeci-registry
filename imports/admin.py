from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from unfold.admin import ModelAdmin

from core.groups import is_chairperson_only

from .forms import ChildFormSet, StagedPersonForm, UploadForm, children_initial, initial_from_data
from .models import ImportBatch, StagedPerson, StagedPersonStatus
from .parsing import ImportValidationError, parse_import_json
from .services import build_person_from_import, duplicate_warning


def _next_pending_row(batch, after_sequence=None):
    pending = batch.rows.filter(status=StagedPersonStatus.PENDING)
    if after_sequence is not None:
        after = pending.filter(sequence__gt=after_sequence).order_by("sequence").first()
        if after is not None:
            return after
    return pending.order_by("sequence").first()


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

    # -- upload -------------------------------------------------------------

    def upload_view(self, request):
        self._require_reviewer(request, "imports.add_importbatch")
        errors: list[str] = None
        if request.method == "POST":
            form = UploadForm(request.POST, request.FILES)
            if form.is_valid():
                raw = form.cleaned_data["file"].read()
                try:
                    entries = parse_import_json(raw)
                except ImportValidationError as exc:
                    errors = exc.errors
                else:
                    batch = ImportBatch.objects.create(
                        source_filename=form.cleaned_data["file"].name,
                        uploaded_by=request.user,
                    )
                    StagedPerson.objects.bulk_create(
                        StagedPerson(batch=batch, sequence=index, raw_data=entry)
                        for index, entry in enumerate(entries)
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

    # -- progress / batch detail ---------------------------------------

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self._require_reviewer(request, "imports.view_importbatch")
        batch = get_object_or_404(ImportBatch, pk=object_id)
        rows = batch.rows.select_related("created_person").order_by("sequence")
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
        }
        return render(request, "admin/imports/importbatch/progress.html", context)

    # -- per-person review --------------------------------------------

    def review_view(self, request, batch_id, row_id):
        self._require_reviewer(request, "imports.change_stagedperson")
        batch = get_object_or_404(ImportBatch, pk=batch_id)
        row = get_object_or_404(StagedPerson, pk=row_id, batch=batch)

        read_only = row.status != StagedPersonStatus.PENDING

        if request.method == "POST" and not read_only:
            action = request.POST.get("action")

            if action == "skip":
                target = _next_pending_row(batch, after_sequence=row.sequence)
                if target:
                    return redirect("admin:imports_importbatch_review", batch.pk, target.pk)
                return redirect("admin:imports_importbatch_change", batch.pk)

            if action == "reject":
                row.status = StagedPersonStatus.REJECTED
                row.error_message = ""
                row.reviewed_by = request.user
                row.reviewed_at = timezone.now()
                row.save()
                self.message_user(request, f"Rejected {row}.", messages.WARNING)
                target = _next_pending_row(batch, after_sequence=row.sequence)
                if target:
                    return redirect("admin:imports_importbatch_review", batch.pk, target.pk)
                return redirect("admin:imports_importbatch_change", batch.pk)

            if action == "approve":
                form = StagedPersonForm(request.POST)
                formset = ChildFormSet(request.POST, prefix="children")
                if form.is_valid() and formset.is_valid():
                    cleaned = dict(form.cleaned_data)
                    children = [c for c in formset.cleaned_data if c.get("full_name")]
                    row.edited_data = {**row.effective_data, **cleaned}
                    row.edited_data["children"] = children
                    try:
                        person = build_person_from_import(cleaned, children, request.user)
                    except ValidationError as exc:
                        row.error_message = "; ".join(exc.messages)
                        row.save()
                        self.message_user(
                            request,
                            f"Could not approve {row}: {row.error_message}",
                            messages.ERROR,
                        )
                    else:
                        row.status = StagedPersonStatus.APPROVED
                        row.error_message = ""
                        row.created_person = person
                        row.reviewed_by = request.user
                        row.reviewed_at = timezone.now()
                        row.save()
                        warning = duplicate_warning(person)
                        if warning:
                            self.message_user(request, warning, messages.WARNING)
                        self.message_user(request, f"Approved {person.full_name}.", messages.SUCCESS)
                        target = _next_pending_row(batch, after_sequence=row.sequence)
                        if target:
                            return redirect("admin:imports_importbatch_review", batch.pk, target.pk)
                        return redirect("admin:imports_importbatch_change", batch.pk)
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

        context = {
            **self.admin_site.each_context(request),
            "title": f"Review {row}",
            "opts": self.model._meta,
            "batch": batch,
            "row": row,
            "raw_data": row.raw_data,
            "uncertain_fields": row.raw_data.get("uncertain_fields") or [],
            "ai_notes": row.raw_data.get("notes"),
            "confidence": row.raw_data.get("confidence"),
            "form": form,
            "formset": formset,
            "read_only": read_only,
            "counts": batch.counts(),
        }
        return render(request, "admin/imports/importbatch/review.html", context)
