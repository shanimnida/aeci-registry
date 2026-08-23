from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

# Re-register the stock auth admin with Unfold's ModelAdmin so the account
# screens (used by ICT to create logins and manage groups — see
# core.groups) get the same styled widgets as the rest of AEGIS, not a
# plain, unstyled version sitting inside an otherwise themed shell.
admin.site.unregister(User)
admin.site.unregister(Group)


class AegisUserChangeForm(UserChangeForm):
    """The account form, with Django's per-user permission picker removed.

    AEGIS grants nothing to individuals. Every capability in spec 4 belongs
    to one of five groups, and `core.groups` is the single place that says
    what each one can do. The stock form's "User permissions" box —
    sixty-odd rows of "Committees | church position | Can add appointment"
    in a dual-list widget — could therefore only ever be used to give
    somebody access their ROLE does not have: access no group audit would
    show, that nothing in this project reads, and that survives being moved
    between groups. It was also, by a distance, the hardest thing on the
    page to read.

    Groups become plain checkboxes for the same reason. There are five of
    them with real names; a filter-and-shuttle widget for five checkboxes
    is machinery standing in front of a simple question.
    """

    class Meta(UserChangeForm.Meta):
        exclude = ("user_permissions",)
        widgets = {"groups": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "groups" in self.fields:
            self.fields["groups"].help_text = (
                "The role this account holds. Almost everyone has exactly one."
            )


@admin.register(User)
class AegisUserAdmin(UserAdmin, ModelAdmin):
    # Subclassing Unfold's ModelAdmin is not enough on its own for these
    # screens. UserAdmin declares its own three forms, and Django uses those
    # declarations rather than the ModelAdmin's widget styling, so the
    # add-user page, the edit page and the password-change page all rendered
    # as bare unstyled inputs inside a themed shell — the "create a user"
    # screen worst of all, since it is nothing but the two password boxes.
    form = AegisUserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    # The dual-list shuttle widget, gone with the field it was for.
    filter_horizontal = ()

    list_display = ("username", "first_name", "last_name", "role_summary", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "groups")
    readonly_fields = ("last_login", "date_joined", "individual_permissions")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Who they are", {"fields": ("first_name", "last_name", "email")}),
        (
            "Access",
            {
                "fields": ("is_active", "is_staff", "groups"),
                "description": (
                    "<strong>Staff status</strong> is what lets someone log in "
                    "at all — without it the right password still fails. The "
                    "group below is what they can then do."
                ),
            },
        ),
        (
            "Advanced",
            {
                "classes": ("collapse",),
                "fields": ("is_superuser", "individual_permissions", "last_login", "date_joined"),
                "description": (
                    "A superuser bypasses every permission check in AEGIS, "
                    "including the chairperson field restrictions. Grant it to "
                    "ICT only, and prefer the ICT group where it will do."
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
                "description": (
                    "Set a temporary password and give it to the person in "
                    "person or by phone, not in writing. They can change it "
                    "afterwards. On the next screen, tick <strong>Staff "
                    "status</strong> and choose their group — without staff "
                    "status they cannot log in at all, even with the right "
                    "password."
                ),
            },
        ),
    )

    @admin.display(description="Role")
    def role_summary(self, obj):
        if obj.is_superuser:
            return "Superuser"
        names = list(obj.groups.values_list("name", flat=True))
        return ", ".join(names) if names else "—"

    @admin.display(description="Individual permissions")
    def individual_permissions(self, obj):
        """Read-only, and normally empty.

        Removing the picker must not make an existing individual grant
        INVISIBLE — access nobody can see is worse than access that is
        merely awkward to edit. So anything already granted directly is
        named here, with what to do about it. Clearing one is a deliberate
        act through the shell, which is the right weight for something that
        should not exist in the first place.
        """
        if obj is None or not obj.pk:
            return "—"
        names = list(obj.user_permissions.values_list("codename", flat=True))
        if not names:
            return "None — this account's access comes entirely from its group, which is how it should be."
        return (
            f"{len(names)} permission(s) granted directly to this account, "
            f"outside any group: {', '.join(sorted(names))}. AEGIS does not "
            "work this way — the access should come from a group instead. "
            "Ask ICT to clear these."
        )


@admin.register(Group)
class AegisGroupAdmin(GroupAdmin, ModelAdmin):
    """The five roles from spec 4.

    Left largely alone: the permission list on a GROUP is the thing that
    actually defines a role, so it belongs on this screen even though it is
    long. It is also not somewhere anyone should be working by hand —
    core/migrations/0002_create_groups.py is what sets these, so that the
    five roles are the same on every deployment rather than whatever each
    volunteer clicked.
    """
