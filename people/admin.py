from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from simple_history.admin import SimpleHistoryAdmin

from committees.models import CommitteeMembership, CommitteeRole
from core.groups import is_chairperson_only, is_ict
from core.numbering import next_member_no
from people.models import Household, HouseholdMember, MembershipStatus, Person
from records.models import AccessLog, FormScan

# Spec D12: enough to run a committee, and nothing more.
CHAIRPERSON_FIELDS = ("first_name", "last_name", "nickname", "mobile_number", "email")


def find_possible_duplicates(person):
    """A soft warning, never a block. Two people genuinely can share a name."""
    matches = Person.objects.filter(
        last_name__iexact=person.last_name, first_name__iexact=person.first_name
    )
    if person.date_of_birth:
        matches = matches.filter(date_of_birth=person.date_of_birth)
    if person.pk:
        matches = matches.exclude(pk=person.pk)
    return matches


def assign_member_numbers(queryset):
    """Give a MEM- number to members who lack one. Never overwrites."""
    assigned = 0
    for person in queryset.filter(
        member_no__isnull=True, membership_status=MembershipStatus.MEMBER
    ):
        person.member_no = next_member_no()
        person.save(update_fields=["member_no"])
        assigned += 1
    return assigned


class HouseholdMemberInline(admin.TabularInline):
    model = HouseholdMember
    extra = 1
    autocomplete_fields = ("household",)


class CommitteeMembershipInline(admin.TabularInline):
    model = CommitteeMembership
    extra = 1
    fields = ("committee", "function", "role", "date_joined", "date_left")
    autocomplete_fields = ("committee", "function")


class FormScanInline(admin.TabularInline):
    model = FormScan
    extra = 0
    fields = ("form_type", "file", "notes")


@admin.register(Person)
class PersonAdmin(SimpleHistoryAdmin):
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
            names = ", ".join(str(p) for p in duplicates[:3])
            self.message_user(
                request,
                f"This may duplicate an existing record: {names}. Saved anyway — "
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


class HouseholdPersonInline(admin.TabularInline):
    """Same rows as HouseholdMemberInline, seen from the household's side.

    The parent link differs, so the field worth autocompleting differs too.
    """

    model = HouseholdMember
    extra = 1
    autocomplete_fields = ("person",)


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "date_of_marriage")
    search_fields = ("name",)
    inlines = (HouseholdPersonInline,)
