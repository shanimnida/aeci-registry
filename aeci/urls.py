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

# Same three screens the sidebar drops (see UNFOLD["SIDEBAR"] in
# settings.py) and for the same reason: Committee and Position change only
# if the church restructures, and Committee Function rides along with
# Committee. Their ModelAdmins stay registered -- unregistering either would
# break the autocomplete widgets on CommitteeMembershipAdmin and PersonAdmin,
# which look up the *registered* admin of the field's target model -- so
# this only strips them out of the app-index listing (the admin/index.html
# and admin/<app_label>/ pages, both built from get_app_list). A user with
# the view permission can still reach the changelist by URL directly.
_HIDDEN_FROM_APP_LIST = {
    ("committees", "committee"),
    ("committees", "committeefunction"),
    ("committees", "position"),
}


def _ordered_get_app_list(self, request, app_label=None):
    app_list = AdminSite.get_app_list(self, request, app_label)
    for app in app_list:
        app["models"] = [
            model
            for model in app["models"]
            if (app["app_label"], model["model"]._meta.model_name)
            not in _HIDDEN_FROM_APP_LIST
        ]
    app_list = [app for app in app_list if app["models"]]
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
