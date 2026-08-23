from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

# Re-register the stock auth admin with Unfold's ModelAdmin so the account
# screens (used by ICT to create logins and manage groups — see
# core.groups) get the same styled widgets as the rest of AEGIS, not a
# plain, unstyled version sitting inside an otherwise themed shell. This
# changes presentation only: UserAdmin/GroupAdmin's own permission
# machinery is untouched.
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class AegisUserAdmin(UserAdmin, ModelAdmin):
    # Subclassing Unfold's ModelAdmin is not enough on its own for the
    # account screens. UserAdmin declares its own three forms, and Django
    # uses those declarations rather than the ModelAdmin's widget styling,
    # so the add-user page, the edit page and the password-change page all
    # rendered as bare unstyled inputs inside a themed shell — the "create
    # a user" screen worst of all, since it is nothing but the two password
    # boxes. Unfold ships drop-in replacements; naming them here is the
    # documented way to make those three screens match the rest of AEGIS.
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    # What ICT actually needs to see when creating a login for a volunteer:
    # who they are, whether they can get in at all, and which role they
    # hold. Staff status is the field most often forgotten (see
    # docs/DEPLOYMENT.md section 7), so it is in the list rather than buried
    # on the form.
    list_display = ("username", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "groups")

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
                "description": (
                    "Set a temporary password and give it to the person in "
                    "person or by phone, not in writing. They can change it "
                    "afterwards. Next, tick <strong>Staff status</strong> and "
                    "add them to a group — without staff status they cannot "
                    "log in at all, even with the right password."
                ),
            },
        ),
    )


@admin.register(Group)
class AegisGroupAdmin(GroupAdmin, ModelAdmin):
    pass
