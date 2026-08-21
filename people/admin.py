from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.models.constants import LOOKUP_SEP
from django.shortcuts import render
from django.urls import path
from django.utils import timezone
from django.utils.text import capfirst
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core.groups import is_chairperson_only, is_ict
from core.numbering import next_member_no, reconcile_member_sequence
from people.models import Household, HouseholdMember, MembershipStatus, Person
from records.models import AccessLog, FormScan

# Spec D12: enough to run a committee, and nothing more.
CHAIRPERSON_FIELDS = ("first_name", "last_name", "nickname", "mobile_number", "email")

# The chase-list report (see missing_data_view below) only ever names a
# field a chairperson could already see elsewhere in this admin -- the
# intersection of what the follow-up queue tracks and what CHAIRPERSON_FIELDS
# permits. Telling a chairperson "home address" or "date of birth" is
# missing would disclose that field exists for that person at all, which
# CHAIRPERSON_FIELDS is deliberately built to prevent everywhere else.
CHAIRPERSON_VISIBLE_TRACKED_FIELDS = tuple(
    field for field in Person.TRACKED_FIELDS if field in CHAIRPERSON_FIELDS
)

MISSING_FIELD_LABELS = {
    field: capfirst(Person._meta.get_field(field).verbose_name)
    for field in Person.TRACKED_FIELDS
}


def find_possible_duplicates(person):
    """A soft warning, never a block. Two people genuinely can share a name.

    An absent date of birth is not evidence of a different person. The six
    chairpersons seed_officers creates from data/officers.csv have no
    date-of-birth column to draw from, so all six sit in the register with
    date_of_birth = NULL -- and one of them submitting their own profiling
    form later, with a real birthdate this time, must still be recognised as
    the same person. So when the candidate carries a birthdate, this matches
    existing same-name records that share that exact birthdate *or* have no
    birthdate on file; only a same-name record with a genuinely *different*
    birthdate is excluded. When the candidate has no birthdate of its own,
    matching stays name-only, exactly as before.
    """
    matches = Person.objects.filter(
        last_name__iexact=person.last_name, first_name__iexact=person.first_name
    )
    if person.date_of_birth:
        matches = matches.filter(
            Q(date_of_birth=person.date_of_birth) | Q(date_of_birth__isnull=True)
        )
    if person.pk:
        matches = matches.exclude(pk=person.pk)
    return matches


def describe_duplicate_match(candidate, date_of_birth):
    """One line of *why* `candidate` matched, for whoever is reviewing the
    warning. A name-and-birthdate match is much stronger evidence than a
    name-only match against a record that simply has no birthdate on file
    (exactly the seeded-officer case above) -- the reviewer should not have
    to guess which kind of match they are looking at.

    Relies on find_possible_duplicates' own filter: when `date_of_birth` is
    given, every candidate in its result either shares that exact date or
    has none at all, so checking candidate.date_of_birth is enough to tell
    the two cases apart without re-comparing the dates here.
    """
    if date_of_birth and candidate.date_of_birth:
        return f"{candidate} (same name and birthdate)"
    if date_of_birth and not candidate.date_of_birth:
        return f"{candidate} (same name; existing record has no birthdate on file)"
    return f"{candidate} (name match only)"


def assign_member_numbers(queryset):
    """Give a MEM- number to members who lack one. Never overwrites.

    Reconciles the MEM sequence against any hand-entered numbers first, so
    an allocation can never collide with a number the Secretariat already
    typed in from a paper form. Called once per invocation (not once per
    row) since reconciliation is a full scan of Person.member_no — see
    core.numbering.reconcile_member_sequence for why that cost is fine here
    but would not be inside next_member_no() itself.
    """
    reconcile_member_sequence()
    assigned = 0
    for person in queryset.filter(
        member_no__isnull=True, membership_status=MembershipStatus.MEMBER
    ):
        person.member_no = next_member_no()
        person.save(update_fields=["member_no"])
        assigned += 1
    return assigned


class HouseholdMemberInline(TabularInline):
    model = HouseholdMember
    # extra = 0: a rendered-but-untouched blank row is not the trap (an
    # unchanged form posts clean either way) -- but *touching* one at all
    # (e.g. clicking into the household autocomplete) makes it a row the
    # formset must validate, and it has no data in it. The volunteer's only
    # way out was ticking Delete on a row they never meant to create.
    # "Add another" is the explicit way in now.
    extra = 0
    autocomplete_fields = ("household",)


class CommitteeMembershipInline(TabularInline):
    model = CommitteeMembership
    extra = 0  # Same trap, same fix -- see HouseholdMemberInline above.
    fields = ("committee", "function", "role", "date_joined", "date_left")
    autocomplete_fields = ("committee", "function")


class FormScanInline(TabularInline):
    model = FormScan
    extra = 0
    fields = ("form_type", "file", "notes")


@admin.register(Person)
class PersonAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "full_name", "member_no", "membership_status", "mobile_number",
        "has_missing_data",
    )
    list_filter = ("membership_status", "has_missing_data", "consent_given")
    search_fields = ("last_name", "first_name", "nickname", "member_no", "mobile_number")
    readonly_fields = ("status_changed_at", "has_missing_data")
    autocomplete_fields = ("approved_by", "guardian", "user")
    inlines = (HouseholdMemberInline, CommitteeMembershipInline, FormScanInline)
    actions = ("assign_member_no",)

    fieldsets = (
        ("Identity", {
            "fields": (
                "member_no", ("last_name", "first_name"), ("middle_name", "suffix"),
                "nickname",
            )
        }),
        ("Personal", {
            "fields": (
                ("date_of_birth", "place_of_birth"), ("gender", "civil_status"),
                "nationality",
            )
        }),
        ("Contact", {"fields": ("home_address", ("mobile_number", "email"))}),
        ("Emergency contact", {
            "fields": (
                "emergency_contact_name", "emergency_contact_relationship",
                "emergency_contact_number",
            )
        }),
        ("Guardian", {"fields": ("guardian", "guardian_relationship")}),
        ("Membership", {
            "fields": (
                "membership_status", "status_changed_at", "date_filed",
                "date_became_member", "approved_by", "date_of_death",
            )
        }),
        ("Privacy", {
            "fields": (
                "consent_given", "consent_date", "consent_version", "greeting_opt_out",
            )
        }),
        ("Follow-up", {"fields": ("has_missing_data", "follow_up_notes", "notes")}),
    )

    @admin.display(description="Name", ordering="last_name")
    def full_name(self, obj):
        return obj.full_name

    @admin.action(description="Assign member numbers", permissions=["change"])
    def assign_member_no(self, request, queryset):
        count = assign_member_numbers(queryset)
        self.message_user(request, f"Assigned {count} member number(s).")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        duplicates = find_possible_duplicates(obj)
        if duplicates.exists():
            descriptions = ", ".join(
                describe_duplicate_match(p, obj.date_of_birth) for p in duplicates[:3]
            )
            self.message_user(
                request,
                f"This may duplicate an existing record: {descriptions}. Saved anyway — "
                f"check and merge by hand if it is the same person.",
                level=messages.WARNING,
            )
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        person = self.get_object(request, object_id)
        if person is not None and self._access_will_be_permitted(request, person):
            AccessLog.record(
                user=request.user,
                person=person,
                ip=request.META.get("REMOTE_ADDR"),
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def _access_will_be_permitted(self, request, obj) -> bool:
        """Mirror what Django is about to enforce, which differs by method.

        _changeform_view accepts view-or-change for a GET but requires change
        for a POST. Gating on the looser rule would log a refused POST from a
        view-only user.
        """
        if request.method == "POST":
            return self.has_change_permission(request, obj)
        return self.has_view_or_change_permission(request, obj)

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
        roster = (
            CommitteeMembership.objects.active()
            .filter(committee_id__in=chaired)
            .values_list("person_id", flat=True)
        )
        return queryset.filter(pk__in=roster)

    def get_fields(self, request, obj=None):
        if is_chairperson_only(request.user):
            return CHAIRPERSON_FIELDS
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if is_chairperson_only(request.user):
            return CHAIRPERSON_FIELDS
        return super().get_readonly_fields(request, obj)

    def get_fieldsets(self, request, obj=None):
        if is_chairperson_only(request.user):
            return ((None, {"fields": CHAIRPERSON_FIELDS}),)
        fieldsets = super().get_fieldsets(request, obj)
        if is_ict(request.user):
            # Linking a login is an ICT action (see core.groups.is_ict) — the
            # Secretariat and everyone else get the fieldsets above, unchanged.
            fieldsets = (*fieldsets, ("Login", {"fields": ("user",)}))
        return fieldsets

    def get_inlines(self, request, obj):
        if is_chairperson_only(request.user):
            return ()
        return super().get_inlines(request, obj)

    def get_list_display(self, request):
        if is_chairperson_only(request.user):
            return ("full_name", "nickname", "mobile_number", "email")
        return super().get_list_display(request)

    def get_list_filter(self, request):
        if is_chairperson_only(request.user):
            return ()
        return super().get_list_filter(request)

    def lookup_allowed(self, lookup, value, request=None):
        # Spec D12 closes here, not just in what's rendered: get_fields,
        # get_fieldsets, get_list_display and get_list_filter all hide the
        # withheld fields from view, but Django's changelist applies any
        # ?field__lookup=value querystring filter *before* rendering, and by
        # default a direct (non-relational) model field is always an allowed
        # lookup regardless of list_filter. Left alone, a chairperson could
        # never see "date_of_birth" on the page yet still binary-search it
        # via repeated ?date_of_birth__year=1985-style requests — nothing
        # displayed, everything disclosed. So for a chairperson-only user,
        # only lookups rooted in one of the five permitted fields may pass;
        # everything else is refused before it ever reaches the queryset.
        if request is not None and is_chairperson_only(request.user):
            root_field = lookup.split(LOOKUP_SEP, 1)[0]
            if root_field not in CHAIRPERSON_FIELDS:
                return False
        return super().lookup_allowed(lookup, value, request)

    def history_view(self, request, object_id, extra_context=None):
        # simple-history's history_view falls back to the raw history manager
        # when get_queryset() hides the object, and renders a full field diff.
        # A chairperson sees five fields; they get no history at all.
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_view(request, object_id, extra_context)

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        if is_chairperson_only(request.user):
            raise PermissionDenied
        return super().history_form_view(request, object_id, version_id, extra_context)

    # -- missing-data chase list ---------------------------------------

    def get_urls(self):
        custom = [
            path(
                "missing-data/",
                self.admin_site.admin_view(self.missing_data_view),
                name="people_person_missing_data",
            ),
        ]
        return custom + super().get_urls()

    def missing_data_view(self, request):
        """The paper chase list: everyone with a gap, and exactly what to ask for.

        A dedicated page rather than a ticked-checkbox admin action -- the
        Secretariat's normal case is "print everyone outstanding", and
        forcing them to select 40 rows first to get there would be the
        wrong default. The ?committee= filter below covers the other real
        case: a chairperson (or the Secretariat, splitting the work) wants
        just one committee's roster to hand a volunteer.

        Reuses get_queryset() and is_chairperson_only() exactly as the rest
        of PersonAdmin does, so whatever a role can already reach through
        the ordinary changelist/detail views is the ceiling here too --
        this view can narrow that further, never widen it.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied

        chairperson_only = is_chairperson_only(request.user)
        visible_fields = (
            CHAIRPERSON_VISIBLE_TRACKED_FIELDS if chairperson_only else Person.TRACKED_FIELDS
        )

        if chairperson_only:
            committees = Committee.objects.filter(
                pk__in=CommitteeMembership.objects.active()
                .filter(
                    person__user=request.user,
                    role__in=(CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR),
                )
                .values_list("committee_id", flat=True)
            ).order_by("name")
        else:
            committees = Committee.objects.filter(is_active=True).order_by("name")

        committee_id = None
        raw_committee_id = request.GET.get("committee") or ""
        if raw_committee_id:
            try:
                committee_id = int(raw_committee_id)
            except ValueError:
                committee_id = None

        queryset = self.get_queryset(request).filter(has_missing_data=True)
        if committee_id is not None:
            roster = (
                CommitteeMembership.objects.active()
                .filter(committee_id=committee_id)
                .values_list("person_id", flat=True)
            )
            queryset = queryset.filter(pk__in=roster)

        entries = []
        for person in queryset:
            missing = [field for field in visible_fields if field in person.missing_fields]
            if not missing:
                # Every gap this person has lives in a field this role
                # cannot see at all -- so, as far as this report is
                # concerned, there is nothing outstanding to report.
                continue
            entries.append(
                {
                    "display_name": (
                        f"{person.first_name} {person.last_name}".strip()
                        if chairperson_only
                        else person.full_name
                    ),
                    "nickname": person.nickname,
                    "mobile_number": person.mobile_number,
                    "email": person.email,
                    "missing_labels": [MISSING_FIELD_LABELS[field] for field in missing],
                }
            )

        report_label = "missing-data chase list"
        if committee_id is not None:
            report_label = f"{report_label} — committee {committee_id}"
        AccessLog.record(
            user=request.user,
            report=report_label[:120],
            ip=request.META.get("REMOTE_ADDR"),
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Missing-data chase list",
            "opts": self.model._meta,
            "entries": entries,
            "printed_at": timezone.now(),
            "committees": committees,
            "selected_committee": raw_committee_id,
            "chairperson_only": chairperson_only,
        }
        return render(request, "admin/people/person/missing_data.html", context)


class HouseholdPersonInline(TabularInline):
    """Same rows as HouseholdMemberInline, seen from the household's side.

    The parent link differs, so the field worth autocompleting differs too.
    """

    model = HouseholdMember
    extra = 0  # Same trap as HouseholdMemberInline above, same fix.
    autocomplete_fields = ("person",)


@admin.register(Household)
class HouseholdAdmin(ModelAdmin):
    list_display = ("name", "date_of_marriage")
    search_fields = ("name",)
    inlines = (HouseholdPersonInline,)
