from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from committees.models import CommitteeMembership
from core.numbering import next_member_no
from people.models import Household, HouseholdMember, MembershipStatus, Person
from records.models import AccessLog, FormScan


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
    autocomplete_fields = ("approved_by", "guardian")
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

    @admin.action(description="Assign member numbers")
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
        if person is not None:
            AccessLog.record(
                user=request.user,
                person=person,
                ip=request.META.get("REMOTE_ADDR"),
            )
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "date_of_marriage")
    search_fields = ("name",)
    inlines = (HouseholdMemberInline,)
