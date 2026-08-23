from collections import defaultdict

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.constants import LOOKUP_SEP
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import path, reverse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, CommitteeRole, Position,
)
from committees.appointing import (
    appointable_committees,
    appointable_people,
    appointable_roles,
    current_officers,
    may_appoint,
    may_end,
)
from committees.derived import bands_for_committee, derived_places, unplaceable_count
from core.groups import is_chairperson_only
from people.admin import CHAIRPERSON_FIELDS
from records.models import AccessLog

# The membership's own fields a chairperson is entitled to filter the
# changelist by directly. `person` is deliberately absent: a bare
# ?person=<id> isn't one of the fields Spec D12 grants, and traversal into
# the related Person is handled separately in lookup_allowed below, limited
# to the same five fields people.admin.PersonAdmin permits.
CHAIRPERSON_OWN_FIELDS = ("committee", "role", "function", "date_joined", "date_left")

# The committee every committee secretary also sits on (requested
# 2026-08-23). Note this is the Secretariat *committee* -- one of the twelve
# on the profiling form -- and NOT the Secretariat permission group in
# core/groups.py, which is what grants edit rights over Person records. The
# two share a name and nothing else; sitting on the committee grants no
# access to anything.
SECRETARIAT_COMMITTEE_CODE = "secretariat"

# Roster sections on the overview and detail screens, in the order they are
# shown. Members last: it is usually the largest, least-special group.
ROSTER_ROLE_ORDER = (
    ("Chairperson", CommitteeRole.CHAIRPERSON),
    ("Co-Chair", CommitteeRole.CO_CHAIR),
    ("Secretary", CommitteeRole.SECRETARY),
    ("Board Oversight", CommitteeRole.OVERSIGHT),
    ("Members", CommitteeRole.MEMBER),
    ("Members by office", CommitteeRole.EX_OFFICIO),
)

# Gaps the church's own Board minutes track (see the overview/detail
# templates' brief). Secretary joined them 2026-08-23, when the church made
# it an office on every committee -- an unfilled one is now a real vacancy,
# the same way an unfilled chair is. An empty Co-Chair, Members or Members
# by office section is unremarkable and shown plainly instead.
ROSTER_GAP_TEXT = {
    CommitteeRole.CHAIRPERSON: "No chairperson assigned",
    CommitteeRole.SECRETARY: "No secretary assigned",
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


def overview_committee_card(committee, memberships, derived=()):
    """One committee's at-a-glance summary for the overview grid.

    `memberships` is already scoped to active rows a caller may see (see
    CommitteeMembershipAdmin.get_queryset) and to just this committee.
    `derived` holds age-band places (committees/derived.py), which count
    toward the headline number because they are real members of that
    committee by the Board's rule -- but never toward the chairperson,
    secretary or oversight gaps, which are offices nobody holds by age.
    """
    chair = next((m for m in memberships if m.role == CommitteeRole.CHAIRPERSON), None)
    secretary = next((m for m in memberships if m.role == CommitteeRole.SECRETARY), None)
    co_chairs = [m for m in memberships if m.role == CommitteeRole.CO_CHAIR]
    oversight = [m for m in memberships if m.role == CommitteeRole.OVERSIGHT]
    # An appointed body has no officers by design, so an empty post is not
    # a vacancy and reporting it as one is noise on a screen whose whole job
    # is showing real gaps (see Committee.has_officers).
    officer_gaps = committee.has_officers
    return {
        "committee": committee,
        "count": len(memberships) + len(derived),
        "derived_count": len(derived),
        "is_empty": not memberships and not derived,
        "has_officers": committee.has_officers,
        "missing_chair": officer_gaps and chair is None,
        "missing_secretary": officer_gaps and secretary is None,
        "missing_oversight": officer_gaps and not oversight,
        "chair_name": overview_display_name(chair.person) if chair else "",
        "secretary_name": overview_display_name(secretary.person) if secretary else "",
        "co_chair_names": [overview_display_name(m.person) for m in co_chairs],
        "oversight_names": [overview_display_name(m.person) for m in oversight],
    }


def overview_roster_row(membership):
    """One roster line, from either a real membership or a derived place.

    Both carry `person` and a function name; only a real membership has a
    `function` foreign key, so the derived stand-in supplies
    `function_name` instead and this reads whichever is there.
    """
    person = membership.person
    is_derived = getattr(membership, "is_derived", False)
    if is_derived:
        function = membership.function_name
    else:
        function = membership.function.name if membership.function_id else ""
    return {
        "name": overview_display_name(person),
        "function": function,
        "mobile_number": person.mobile_number,
        "email": person.email,
        "is_derived": is_derived,
        "band": getattr(membership, "band", ""),
    }


def overview_roster_sections(memberships, derived=()):
    """Group a committee's memberships into role sections, in display order,
    each carrying its own gap message when it applies.

    `derived` holds places that follow from the Board's age bands rather
    than from a recorded decision (see committees/derived.py). They join the
    Members section, since that is what they are, and each row says so --
    a roster that showed them as indistinguishable from a membership
    somebody typed would be claiming a decision nobody made.
    """
    sections = []
    for label, role in ROSTER_ROLE_ORDER:
        rows = [m for m in memberships if m.role == role]
        entries = [overview_roster_row(m) for m in rows]
        if role == CommitteeRole.MEMBER:
            entries += [overview_roster_row(place) for place in derived]
        sections.append({
            "label": label,
            "rows": entries,
            "gap_text": ROSTER_GAP_TEXT.get(role) if not entries else None,
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
        self._report_secretariat_seat(request, obj)

    def _report_secretariat_seat(self, request, obj):
        """Say what the automatic Secretariat seat just did.

        The Board's rule is that every committee secretary IS a member of
        the Secretariat committee -- not that they may be -- so
        CommitteeMembership.save() keeps that seat in step and this only
        reports it. An earlier build prompted instead; the church confirmed
        the rule is automatic, and a prompt somebody ignores leaves the
        roster contradicting the church's own rule.
        """
        if obj.role != CommitteeRole.SECRETARY:
            return
        if obj.committee.code == SECRETARIAT_COMMITTEE_CODE:
            return
        seat = (
            CommitteeMembership.objects.active()
            .filter(
                person=obj.person,
                committee__code=SECRETARIAT_COMMITTEE_CODE,
                role=CommitteeRole.EX_OFFICIO,
            )
            .exists()
        )
        if seat:
            self.message_user(
                request,
                f"{obj.person.full_name} also sits on the Secretariat committee, "
                "recorded automatically — every committee secretary does.",
                level=messages.INFO,
            )
        else:
            self.message_user(
                request,
                f"{obj.person.full_name} no longer holds a secretary post, so "
                "their Secretariat seat has been ended too.",
                level=messages.INFO,
            )

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

        cards = []
        for committee in committees:
            rows = by_committee.get(committee.pk, [])
            # A chairperson's own view is already narrowed to their roster;
            # adding an age-derived list would show them people they were
            # never given. The count they see stays what get_queryset allows.
            derived = (
                []
                if chairperson_only
                else derived_places(
                    committee, exclude_person_ids={row.person_id for row in rows}
                )
            )
            cards.append(overview_committee_card(committee, rows, derived))

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

        derived = (
            []
            if is_chairperson_only(request.user)
            else derived_places(
                committee, exclude_person_ids={m.person_id for m in memberships}
            )
        )

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
            "count": len(memberships) + len(derived),
            "functions": list(committee.functions.all()),
            "sections": overview_roster_sections(memberships, derived),
            "derived_count": len(derived),
            "age_rule_applies": bool(bands_for_committee(committee.code)),
            "unplaceable": unplaceable_count() if bands_for_committee(committee.code) else 0,
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

    # -- committee appointments ----------------------------------------

    def get_urls(self):
        custom = [
            path(
                "committees/",
                self.admin_site.admin_view(self.appoint_view),
                name="committees_appointment_appoint",
            ),
        ]
        return custom + super().get_urls()

    def appoint_view(self, request):
        """One place for committee appointments: chairpersons, co-chairs,
        secretaries and Board oversight.

        Requested 2026-08-24, and it is the Board's own structure: the Board
        appoints each committee's chairperson, and each chairperson appoints
        their own vice and secretary.

        Access does NOT come from a model permission. The Chairperson group
        is deliberately left without add_committeemembership, because a
        chairperson who could reach the ordinary add form could put anyone
        on any committee in any role. The gate is committees.appointing,
        which narrows by committee, by role and by person all at once -- see
        that module for why a chairperson picking from their own roster is
        what makes this screen reachable by them at all.
        """
        if not may_appoint(request.user):
            raise PermissionDenied

        committees = list(appointable_committees(request.user))
        roles = appointable_roles(request.user)

        if request.method == "POST":
            return self._handle_appointment(request, committees, roles)

        AccessLog.record(
            user=request.user,
            report="committee appointments",
            ip=request.META.get("REMOTE_ADDR"),
        )
        context = {
            **self.admin_site.each_context(request),
            "title": "Committee appointments",
            "opts": self.model._meta,
            "today": timezone.localdate().isoformat(),
            "role_choices": [
                (role, CommitteeRole(role).label) for role in roles
            ],
            "blocks": [
                {
                    "committee": committee,
                    "officers": [
                        {
                            "membership": membership,
                            "can_end": may_end(request.user, membership),
                        }
                        for membership in current_officers(committee)
                    ],
                    "candidates": appointable_people(request.user, committee),
                }
                for committee in committees
            ],
            "is_chairperson_only": is_chairperson_only(request.user),
        }
        return render(
            request, "admin/committees/appointment/appoint.html", context
        )

    def _handle_appointment(self, request, committees, roles):
        redirect_to = redirect("admin:committees_appointment_appoint")
        committee = next(
            (c for c in committees if str(c.pk) == request.POST.get("committee")), None
        )
        if committee is None:
            self.message_user(
                request,
                "That committee is not yours to appoint on.",
                level=messages.ERROR,
            )
            return redirect_to

        if request.POST.get("action") == "end":
            membership = (
                CommitteeMembership.objects.active()
                .filter(pk=request.POST.get("membership"), committee=committee)
                .first()
            )
            if membership is None or not may_end(request.user, membership):
                self.message_user(
                    request, "That role is not yours to end.", level=messages.ERROR
                )
                return redirect_to
            membership.date_left = timezone.localdate()
            membership.updated_by = request.user
            membership.full_clean()
            membership.save()
            self.message_user(
                request,
                f"Ended {membership.person.full_name} as "
                f"{membership.get_role_display()} of {committee.name}.",
                level=messages.SUCCESS,
            )
            return redirect_to

        role = request.POST.get("role")
        if role not in roles:
            self.message_user(
                request, "That role is not yours to appoint.", level=messages.ERROR
            )
            return redirect_to

        person = appointable_people(request.user, committee).filter(
            pk=request.POST.get("person")
        ).first()
        if person is None:
            self.message_user(
                request,
                "That person is not one you can appoint on this committee.",
                level=messages.ERROR,
            )
            return redirect_to

        # Somebody already serving on this committee is PROMOTED, not added
        # again: one person holds one role on a committee at a time (R59),
        # and their service is continuous -- they joined when they joined and
        # today they took an office. simple-history records when the role
        # changed, which is where "since when" for the office itself lives.
        membership = (
            CommitteeMembership.objects.active()
            .filter(committee=committee, person=person)
            .exclude(date_left__lte=timezone.localdate())
            .first()
        )
        if membership is None:
            membership = CommitteeMembership(
                committee=committee,
                person=person,
                role=role,
                date_joined=timezone.localdate(),
                created_by=request.user,
                updated_by=request.user,
            )
        else:
            membership.role = role
            membership.updated_by = request.user
        try:
            # The church's rules live in clean() and save() skips it: one
            # chairperson, one secretary, one role per committee, oversight
            # only for the Board.
            membership.full_clean()
        except ValidationError as error:
            self.message_user(request, "; ".join(error.messages), level=messages.ERROR)
            return redirect_to
        membership.save()
        self.message_user(
            request,
            f"Appointed {person.full_name} as {membership.get_role_display()} "
            f"of {committee.name}.",
            level=messages.SUCCESS,
        )
        return redirect_to
