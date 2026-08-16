from django.contrib import admin

from records.models import AccessLog, FormScan


@admin.register(FormScan)
class FormScanAdmin(admin.ModelAdmin):
    list_display = ("form_type", "person", "uploaded_by", "uploaded_at")
    list_filter = ("form_type",)
    autocomplete_fields = ("person",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "person", "report", "ip_address")
    list_filter = ("user",)
    readonly_fields = ("user", "person", "report", "timestamp", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
