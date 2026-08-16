from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin

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
    pass


@admin.register(Group)
class AegisGroupAdmin(GroupAdmin, ModelAdmin):
    pass
