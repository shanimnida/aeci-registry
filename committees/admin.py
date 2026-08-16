from django.contrib import admin
from django.core.exceptions import PermissionDenied
from simple_history.admin import SimpleHistoryAdmin

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, CommitteeRole, Position,
)
from core.groups import is_chairperson_only


class CommitteeFunctionInline(admin.TabularInline):
    model = CommitteeFunction
    extra = 0


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_self_selectable", "is_active")
    list_filter = ("is_self_selectable", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}
    inlines = (CommitteeFunctionInline,)


@admin.register(CommitteeFunction)
class CommitteeFunctionAdmin(admin.ModelAdmin):
    list_display = ("committee", "name")
    search_fields = ("name", "committee__name")


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(SimpleHistoryAdmin):
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

    def history_view(self, request, object_id, extra_context=None):
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_view(request, object_id, extra_context)

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_form_view(request, object_id, version_id, extra_context)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_unique_holder")
    search_fields = ("name",)


@admin.register(Appointment)
class AppointmentAdmin(SimpleHistoryAdmin):
    list_display = ("person", "position", "start_date", "end_date")
    list_filter = ("position",)
    search_fields = ("person__last_name", "person__first_name")
    autocomplete_fields = ("person",)
