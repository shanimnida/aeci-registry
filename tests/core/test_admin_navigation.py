"""The 2026-08-21 sidebar decluttering: Committee, Committee Function and
Position drop out of the navigation (they change only if the church
restructures) while Committee Membership and Appointment stay, and the
audit/system screens (Form scans, Access logs, Purge records, Users, Groups)
move into one de-emphasized group at the bottom.

Every ModelAdmin involved stays *registered* -- only its appearance in the
admin index (aeci/urls.py's get_app_list override) and the Unfold sidebar
(settings.py UNFOLD["SIDEBAR"]) changes. The risk that matters most: Django's
autocomplete widget looks up the target field's *registered* ModelAdmin
(django.contrib.admin.views.autocomplete.AutocompleteJsonView.process_request
calls admin_site.get_model_admin(remote_model)), so unregistering Committee
or CommitteeFunction would silently break the committee/function pickers on
the Committee Membership and Person screens. These tests exercise that real
endpoint rather than trusting the settings diff.
"""
import pytest
from django.contrib.auth.models import Group, User

from committees.models import Committee, CommitteeFunction
from core import groups

HIDDEN_CHANGELISTS = (
    "/admin/committees/committee/",
    "/admin/committees/committeefunction/",
    "/admin/committees/position/",
)
VISIBLE_COMMITTEE_CHANGELISTS = (
    "/admin/committees/committeemembership/",
    "/admin/committees/appointment/",
)
SYSTEM_CHANGELISTS = (
    "/admin/records/formscan/",
    "/admin/records/accesslog/",
    "/admin/records/purgerecord/",
    "/admin/auth/user/",
    "/admin/auth/group/",
)


@pytest.fixture
def ict_user(db):
    user = User.objects.create_user("ict-nav", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.ICT))
    return user


@pytest.fixture
def secretariat_user(db):
    user = User.objects.create_user("sec-nav", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    return user


@pytest.fixture
def chairperson_user(db):
    user = User.objects.create_user("chair-nav", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    return user


def _hrefs_present(body, paths):
    return {path: (f'href="{path}"' in body) for path in paths}


# -- admin index (app list) -------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("user_fixture", ["ict_user", "secretariat_user"])
def test_hidden_models_absent_from_admin_index(client, request, user_fixture):
    """ICT and Secretariat both hold view_committee/view_committeefunction/
    view_position (core/migrations), so before this change the app-index
    page would have listed all three. Holding the permission is not enough
    to earn a spot on the index now -- only the direct URL.
    """
    client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/admin/")
    assert response.status_code == 200
    body = response.content.decode()
    presence = _hrefs_present(body, HIDDEN_CHANGELISTS)
    assert not any(presence.values()), presence


@pytest.mark.django_db
def test_visible_committee_screens_still_listed_on_admin_index_for_ict(client, ict_user):
    client.force_login(ict_user)
    body = client.get("/admin/").content.decode()
    for path in VISIBLE_COMMITTEE_CHANGELISTS:
        assert f'href="{path}"' in body, path


@pytest.mark.django_db
def test_hidden_models_also_absent_from_the_committees_app_index_page(client, ict_user):
    """/admin/committees/ is a second, separate route (AdminSite.app_index)
    that also calls get_app_list -- must be filtered too, not just the
    front page.
    """
    client.force_login(ict_user)
    response = client.get("/admin/committees/")
    assert response.status_code == 200
    body = response.content.decode()
    presence = _hrefs_present(body, HIDDEN_CHANGELISTS)
    assert not any(presence.values()), presence
    for path in VISIBLE_COMMITTEE_CHANGELISTS:
        assert f'href="{path}"' in body, path


# -- direct URLs still work --------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("path", HIDDEN_CHANGELISTS)
def test_hidden_models_direct_urls_still_load_for_ict(client, ict_user, path):
    client.force_login(ict_user)
    response = client.get(path)
    assert response.status_code == 200


# -- autocomplete: the thing most likely to break ---------------------------


@pytest.mark.django_db
def test_committee_autocomplete_still_returns_results_on_membership_add_screen(
    client, secretariat_user
):
    """Exercises the real /admin/autocomplete/ endpoint the Committee
    Membership add screen's committee widget calls, exactly as the browser
    would -- not a settings inspection.
    """
    ict = Committee.objects.get(code="ict")
    client.force_login(secretariat_user)
    response = client.get(
        "/admin/autocomplete/",
        {
            "app_label": "committees",
            "model_name": "committeemembership",
            "field_name": "committee",
            "term": "ICT",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert any(result["id"] == str(ict.pk) for result in data["results"]), data


@pytest.mark.django_db
def test_committee_function_autocomplete_still_returns_results(client, secretariat_user):
    """Same endpoint, the function field -- CommitteeFunctionAdmin is the
    other registration the Committee Membership and Person screens depend
    on for autocomplete.
    """
    sunshine = Committee.objects.get(code="sunshine")
    transport = CommitteeFunction.objects.get(committee=sunshine, name="Transport")
    client.force_login(secretariat_user)
    response = client.get(
        "/admin/autocomplete/",
        {
            "app_label": "committees",
            "model_name": "committeemembership",
            "field_name": "function",
            "term": "Transport",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert any(result["id"] == str(transport.pk) for result in data["results"]), data


@pytest.mark.django_db
def test_committee_membership_add_form_renders_with_working_autocomplete_widget(
    client, secretariat_user
):
    """The add screen itself (not just the AJAX endpoint) must render --
    proof CommitteeAdmin's continued registration doesn't just satisfy the
    endpoint but the widget that calls it.
    """
    client.force_login(secretariat_user)
    response = client.get("/admin/committees/committeemembership/add/")
    assert response.status_code == 200
    assert b"admin/autocomplete/" in response.content


# -- roles see only what they can use ---------------------------------------


@pytest.mark.django_db
def test_chairperson_sees_no_link_to_a_screen_that_would_refuse_them(client, chairperson_user):
    """The Chairperson group holds only view_person, view_committee and
    view_committeemembership (core/migrations/0002_create_groups.py). Every
    other changelist in the navigation -- including the ones this branch
    just hid -- must not appear as a link for this role.
    """
    client.force_login(chairperson_user)
    body = client.get("/admin/").content.decode()
    presence = _hrefs_present(
        body,
        HIDDEN_CHANGELISTS
        + ("/admin/committees/appointment/", "/admin/imports/importbatch/", "/admin/people/household/")
        + SYSTEM_CHANGELISTS,
    )
    assert not any(presence.values()), presence


@pytest.mark.django_db
def test_chairperson_sees_the_two_screens_they_actually_use(client, chairperson_user):
    client.force_login(chairperson_user)
    body = client.get("/admin/").content.decode()
    assert 'href="/admin/people/person/"' in body
    assert 'href="/admin/committees/committeemembership/"' in body


@pytest.mark.django_db
def test_chairperson_gets_403_on_screens_they_hold_no_permission_for(client, chairperson_user):
    client.force_login(chairperson_user)
    for path in ("/admin/committees/appointment/", "/admin/records/accesslog/", "/admin/imports/importbatch/"):
        response = client.get(path)
        assert response.status_code == 403, path


@pytest.mark.django_db
def test_chairperson_can_still_reach_committee_directly_since_they_hold_the_permission(
    client, chairperson_user
):
    """Committee is hidden from every role's navigation, including a
    Chairperson's, even though the Chairperson group happens to hold
    view_committee -- hiding is about clutter, not access. A user who holds
    the permission must still be able to reach the screen by URL.
    """
    client.force_login(chairperson_user)
    response = client.get("/admin/committees/committee/")
    assert response.status_code == 200
