from collections import defaultdict

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models.constants import LOOKUP_SEP
from django.shortcuts import get_object_or_404, render
from django.urls import path
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, CommitteeRole, Position,
)
from core.groups import is_chairperson_only
from people.admin import CHAIRPERSON_FIELDS
from records.models import AccessLog

# The membership's own fields a chairperson is entitled to filter the
# changelist by directly. `person` is deliberately absent: a bare
# ?person=<id> isn't one of the fields Spec D12 grants, and traversal into
# the related Person is handled separately in lookup_allowed below, limited
# to the same five fields people.admin.PersonAdmin permits.
CHAIRPERSON_OWN_FIELDS = ("committee", "role", "function", "date_joined", "date_left")

# Roster sections on the overview and detail screens, in the order they are
# shown. Members last: it is usually the largest, least-special group.
ROSTER_ROLE_ORDER = (
    ("Chairperson", CommitteeRole.CHAIRPERSON),
    ("Co-Chair", CommitteeRole.CO_CHAIR),
    ("Board Oversight", CommitteeRole.OVERSIGHT),
    ("Members", CommitteeRole.MEMBER),
)

# Only "no chairperson" and "no oversight" are gaps the church's own Board
# minutes track (see the overview/detail templates' brief) -- an empty
# Co-Chair or Members section is unremarkable and shown plainly instead.
ROSTER_GAP_TEXT = {
    CommitteeRole.CHAIRPERSON: "No chairperson assigned",
    CommitteeRole.OVERSIGHT: "No Board Oversight assigned",
}


def overview_display_name(person):
    """First + last name only, plus a nickname -- deliberately never the
    fuller `Person.full_name` (which also folds in middle name and suffix).

    Every role sees this same shortened form on the committee overview and
    its drill-down, not just a chairperson: the screen exists to answer
    "who chairs it, how many, what's missing", not to be a second full
    directory, so there is nothing to show a wider-access role here that a
    chairperson may not -- and so nothing to branch on by role at all. A
    person's full name remains visible, as before, on their own record in
    the People admin for whoever holds that permission.
    """
    name = f"{person.first_name} {person.last_name}".strip()
    if person.nickname:
        name = f'{name} "{person.nickname}"'
    return name


def overview_committee_card(committee, memberships):
    """One committee's at-a-glance summary for the overview grid.

    `memberships` is already scoped to active rows a caller may see (see
    CommitteeMembershipAdmin.get_queryset) and to just this committee.
    """
    chair = next((m for m in memberships if m.role == CommitteeRole.CHAIRPERSON), None)
    co_chairs = [m for m in memberships if m.role == CommitteeRole.CO_CHAIR]
    oversight = [m for m in memberships if m.role == CommitteeRole.OVERSIGHT]
    return {
        "committee": committee,
        "count": len(memberships),
        "is_empty": not memberships,
        "missing_chair": chair is None,
        "missing_oversight": not oversight,
        "chair_name": overview_display_name(chair.person) if chair else "",
        "co_chair_names": [overview_display_name(m.person) for m in co_chairs],
        "oversight_names": [overview_display_name(m.person) for m in oversight],
    }


def overview_roster_row(membership):
    person = membership.person
    return {
        "name": overview_display_name(person),
        "function": membership.function.name if membership.function_id else "",
        "mobile_number": person.mobile_number,
        "email": person.email,
    }


def overview_roster_sections(memberships):
    """Group a committee's memberships into the four role sections, in
    display order, each carrying its own gap message when it applies.
    """
    sections = []
    for label, role in ROSTER_ROLE_ORDER:
        rows = [m for m in memberships if m.role == role]
        sections.append({
            "label": label,
            "rows": [overview_roster_row(m) for m in rows],
            "gap_text": ROSTER_GAP_TEXT.get(role) if not rows else None,
        })
    return sections


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

    def save_model(self, request, obj, form, change):
        # A soft warning, never a block -- same shape as
        # people.admin.PersonAdmin.save_model's duplicate-person warning.
        # See CommitteeMembership.self_selected_overflow_count for why the
        # cap stopped being a hard refusal on 2026-08-17.
        overflow = obj.self_selected_overflow_count()
        if overflow is not None:
            self.message_user(
                request,
                f"{obj.person.full_name} now serves on {overflow} self-selected "
                f"committees. The profiling form asks for up to "
                f"{obj.SELF_SELECTED_LIMIT}. Saved anyway — check against the "
                "paper form if this looks wrong.",
                level=messages.WARNING,
            )
        super().save_model(request, obj, form, change)

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

    # -- committee overview ----------------------------------------------
    #
    # The landing screen a volunteer reaches from the sidebar (see the
    # "Committee memberships" entry in aeci/settings.py's UNFOLD config):
    # twelve cards answering "who chairs it, how many people, is oversight
    # assigned, what's missing" without opening a single row, instead of a
    # flat table read one membership at a time. This replaces the *landing*
    # view only -- the ordinary changelist above stays registered and
    # reachable (both screens link to each other) for adding and editing,
    # which does not change at all.
    #
    # Row visibility is delegated entirely to get_queryset(), the same
    # method the changelist itself already goes through -- no second,
    # parallel notion of "what a chairperson may see" is written here.

    def get_urls(self):
        custom = [
            path(
                "overview/",
                self.admin_site.admin_view(self.overview_view),
                name="committees_committeemembership_overview",
            ),
            path(
                "overview/<int:committee_id>/",
                self.admin_site.admin_view(self.committee_detail_view),
                name="committees_committeemembership_overview_detail",
            ),
        ]
        return custom + super().get_urls()

    def overview_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        chairperson_only = is_chairperson_only(request.user)

        memberships = (
            self.get_queryset(request)
            .active()
            .select_related("person", "committee")
            .order_by("committee__name", "role", "person__last_name")
        )
        by_committee = defaultdict(list)
        for membership in memberships:
            by_committee[membership.committee_id].append(membership)

        if chairperson_only:
            # Only committees this user actually chairs or co-chairs ever
            # appear in by_committee at all, since get_queryset() already
            # narrowed `memberships` to those before this loop ran.
            committees = Committee.objects.filter(pk__in=by_committee.keys()).order_by("name")
        else:
            committees = Committee.objects.filter(is_active=True).order_by("name")

        cards = [
            overview_committee_card(committee, by_committee.get(committee.pk, []))
            for committee in committees
        ]

        AccessLog.record(
            user=request.user, report="committee overview", ip=request.META.get("REMOTE_ADDR"),
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Committee overview",
            "opts": self.model._meta,
            "cards": cards,
            "chairperson_only": chairperson_only,
        }
        return render(request, "admin/committees/committeemembership/overview.html", context)

    def committee_detail_view(self, request, committee_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        committee = get_object_or_404(Committee, pk=committee_id)

        memberships = list(
            self.get_queryset(request)
            .active()
            .filter(committee=committee)
            .select_related("person", "function")
            .order_by("role", "person__last_name")
        )
        if is_chairperson_only(request.user) and not memberships:
            # get_queryset() already scopes to committees this user chairs
            # or co-chairs; an empty result here means this committee is
            # not one of them, not that it happens to have no members --
            # refuse outright rather than render a roster of nothing.
            raise PermissionDenied

        AccessLog.record(
            user=request.user,
            report=f"committee roster — {committee.name}"[:120],
            ip=request.META.get("REMOTE_ADDR"),
        )

        context = {
            **self.admin_site.each_context(request),
            "title": committee.name,
            "opts": self.model._meta,
            "committee": committee,
            "count": len(memberships),
            "functions": list(committee.functions.all()),
            "sections": overview_roster_sections(memberships),
        }
        return render(
            request, "admin/committees/committeemembership/committee_detail.html", context
        )


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
