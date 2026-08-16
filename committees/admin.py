from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models.constants import LOOKUP_SEP
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, CommitteeRole, Position,
)
from core.groups import is_chairperson_only
from people.admin import CHAIRPERSON_FIELDS

# The membership's own fields a chairperson is entitled to filter the
# changelist by directly. `person` is deliberately absent: a bare
# ?person=<id> isn't one of the fields Spec D12 grants, and traversal into
# the related Person is handled separately in lookup_allowed below, limited
# to the same five fields people.admin.PersonAdmin permits.
CHAIRPERSON_OWN_FIELDS = ("committee", "role", "function", "date_joined", "date_left")


class CommitteeFunctionInline(TabularInline):
    model = CommitteeFunction
    extra = 0


@admin.register(Committee)
class CommitteeAdmin(ModelAdmin):
    list_display = ("name", "code", "is_self_selectable", "is_active")
    list_filter = ("is_self_selectable", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}
    inlines = (CommitteeFunctionInline,)


@admin.register(CommitteeFunction)
class CommitteeFunctionAdmin(ModelAdmin):
    list_display = ("committee", "name")
    search_fields = ("name", "committee__name")


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("person", "committee", "role", "function", "date_joined", "date_left")
    list_filter = ("committee", "role")
    search_fields = ("person__last_name", "person__first_name")
    autocomplete_fields = ("person", "committee", "function")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_chairperson_only(request.user):
            return queryset
        chaired = (
            CommitteeMembership.objects.active()
            .filter(
                person__user=request.user,
                role__in=(CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR),
            )
            .values_list("committee_id", flat=True)
        )
        return queryset.filter(committee_id__in=chaired)

    def lookup_allowed(self, lookup, value, request=None):
        # Same defect as people.admin.PersonAdmin.lookup_allowed, same fix
        # shape, smaller blast radius: get_queryset row-scopes which
        # memberships a chairperson sees, but that happens *after* Django's
        # changelist applies any ?field__lookup=value querystring filter.
        # `person` is a two-level relation here rather than a local field, so
        # Django's own default (a bare, non-relational field is always
        # allowed; a relation crossing is allowed only when it matches
        # list_filter) already blocks most of this by accident — but not on
        # purpose, and not completely: nothing stops list_filter from someday
        # growing a `person__...` entry. So this is explicit rather than
        # relying on that accident. For a chairperson-only user: the
        # membership's own fields may be filtered (and, through them,
        # deferred to Django's normal list_filter check — so no *further*
        # traversal through `committee` or `function` is granted just because
        # the root field is), a `person__` traversal is allowed only into one
        # of the same five fields PersonAdmin permits, and everything else is
        # refused before it ever reaches the queryset.
        if request is not None and is_chairperson_only(request.user):
            parts = lookup.split(LOOKUP_SEP)
            root_field = parts[0]
            if root_field == "person":
                return len(parts) >= 2 and parts[1] in CHAIRPERSON_FIELDS
            if root_field not in CHAIRPERSON_OWN_FIELDS:
                return False
        return super().lookup_allowed(lookup, value, request)

    def history_view(self, request, object_id, extra_context=None):
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_view(request, object_id, extra_context)

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_form_view(request, object_id, version_id, extra_context)


@admin.register(Position)
class PositionAdmin(ModelAdmin):
    list_display = ("name", "code", "is_unique_holder")
    search_fields = ("name",)


@admin.register(Appointment)
class AppointmentAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("person", "position", "start_date", "end_date")
    list_filter = ("position",)
    search_fields = ("person__last_name", "person__first_name")
    autocomplete_fields = ("person",)
