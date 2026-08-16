from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.urls import path

# django-unfold's AppConfig.ready() (see INSTALLED_APPS in settings.py)
# already replaced admin.site with its own AdminSite subclass by the time
# this module is imported — URLconf loads after app registry population.
# The literal "Django administration" / "Django site admin" strings only
# ever surface as template fallbacks when site_title/site_header are falsy;
# UNFOLD["SITE_TITLE"] and UNFOLD["SITE_HEADER"] in settings.py already
# cover that. These two attributes are kept as a second, independent path
# to the same values (index_title is read directly off the site instance,
# not through UNFOLD) and as a safety net if the theme is ever swapped out.
admin.site.site_header = "AEGIS"
admin.site.site_title = "AEGIS"
admin.site.index_title = "Dashboard"

# Friendlier than Django's default "Authentication and Authorization" for a
# volunteer reading the admin index — purely a display string, no
# permissions or registrations are touched.
apps.get_app_config("auth").verbose_name = "Administration"

# The Secretariat's daily work (people, committees, records) belongs above
# the fold; alphabetical order would bury it under "Administration". This
# only resorts an already permission-filtered list — it adds or hides
# nothing a user couldn't already see.
_APP_ORDER = ["people", "committees", "records", "auth", "core"]


def _ordered_get_app_list(self, request, app_label=None):
    app_list = AdminSite.get_app_list(self, request, app_label)
    return sorted(
        app_list,
        key=lambda app: (
            _APP_ORDER.index(app["app_label"])
            if app["app_label"] in _APP_ORDER
            else len(_APP_ORDER)
        ),
    )


admin.site.get_app_list = _ordered_get_app_list.__get__(admin.site, admin.site.__class__)

urlpatterns = [path("admin/", admin.site.urls)]
