import datetime as dt

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, CommitteeRole, Position,
)
from core import groups
from people.models import Person
from records.models import AccessLog

TODAY = dt.date.today()
JOINED = TODAY - dt.timedelta(days=7)


def overview_url():
    return reverse("admin:committees_committeemembership_overview")


def detail_url(committee):
    return reverse(
        "admin:committees_committeemembership_overview_detail", args=[committee.pk]
    )


def make_user(group_name, username="user"):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.mark.django_db
def test_the_overview_shows_all_twelve_committees_for_secretariat_with_matching_counts(client):
    sunshine = Committee.objects.get(code="sunshine")
    chair = Person.objects.create(last_name="Malong", first_name="Shan")
    member = Person.objects.create(last_name="Reyes", first_name="Manex")
    CommitteeMembership.objects.create(
        committee=sunshine, person=chair, role=CommitteeRole.CHAIRPERSON, date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=sunshine, person=member, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(overview_url())
    assert response.status_code == 200

    cards = list(response.context["cards"])
    assert len(cards) == 12
    assert Committee.objects.filter(is_active=True).count() == 12

    sunshine_card = next(c for c in cards if c["committee"].pk == sunshine.pk)
    assert sunshine_card["count"] == 2
    assert sunshine_card["chair_name"] == "Shan Malong"
    assert sunshine_card["missing_chair"] is False


@pytest.mark.django_db
def test_a_committee_with_no_chairperson_is_marked_by_text_and_icon_not_colour_alone(client):
    # A member but no chair -- distinct from the fully-empty case, which
    # gets its own single "nobody assigned" banner instead of this line.
    ict = Committee.objects.get(code="ict")
    member = Person.objects.create(last_name="Reyes", first_name="Manex")
    CommitteeMembership.objects.create(
        committee=ict, person=member, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(overview_url())
    body = response.content.decode()

    ict_card = next(c for c in response.context["cards"] if c["committee"].code == "ict")
    assert ict_card["missing_chair"] is True
    assert ict_card["is_empty"] is False
    # The gap is spelled out in words, and paired with a non-decorative
    # warning icon -- not merely a colour class -- per the "don't convey
    # information by colour alone" rule.
    assert "No chairperson assigned" in body
    assert body.count('material-symbols-outlined') > 0


@pytest.mark.django_db
def test_an_empty_committee_is_marked_as_nobody_assigned(client):
    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(overview_url())
    body = response.content.decode()

    food_card = next(c for c in response.context["cards"] if c["committee"].code == "food")
    assert food_card["is_empty"] is True
    assert food_card["count"] == 0
    assert "Nobody currently assigned" in body


@pytest.mark.django_db
def test_a_departed_member_does_not_count_toward_the_roster(client):
    """active() must be applied on top of the permission-scoped queryset --
    someone who has left shouldn't inflate the headcount or stand in as
    chair."""
    sunshine = Committee.objects.get(code="sunshine")
    left = Person.objects.create(last_name="Cruz", first_name="Ana")
    CommitteeMembership.objects.create(
        committee=sunshine, person=left, role=CommitteeRole.CHAIRPERSON,
        date_joined=JOINED - dt.timedelta(days=100), date_left=JOINED,
    )

    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(overview_url())
    sunshine_card = next(
        c for c in response.context["cards"] if c["committee"].pk == sunshine.pk
    )
    assert sunshine_card["is_empty"] is True
    assert sunshine_card["missing_chair"] is True


@pytest.fixture
def chair_setup(db):
    chair_person = Person.objects.create(
        last_name="Malong", first_name="Shan",
        mobile_number="09170000001", email="shan@example.com",
        date_of_birth=dt.date(1985, 6, 15), home_address="123 Hidden Street",
        civil_status="SINGLE",
    )
    ict = Committee.objects.get(code="ict")
    food = Committee.objects.get(code="food")

    CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON, date_joined=JOINED,
    )
    stranger = Person.objects.create(last_name="Santos", first_name="Rhea")
    CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=JOINED,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, chair_person, ict, food


@pytest.mark.django_db
def test_a_chairperson_only_user_sees_only_their_own_committee_on_the_overview(
    client, chair_setup
):
    user, _, ict, food = chair_setup
    client.force_login(user)
    response = client.get(overview_url())
    body = response.content.decode()

    codes = {c["committee"].code for c in response.context["cards"]}
    assert codes == {"ict"}
    assert "Food" not in body


@pytest.mark.django_db
def test_a_chairperson_sees_no_withheld_field_anywhere_on_overview_or_detail(client, chair_setup):
    user, chair_person, ict, _ = chair_setup
    client.force_login(user)

    overview_response = client.get(overview_url())
    detail_response = client.get(detail_url(ict))

    for body in (overview_response.content.decode(), detail_response.content.decode()):
        assert "1985" not in body
        assert chair_person.home_address not in body
        assert "SINGLE" not in body


@pytest.mark.django_db
def test_a_chairperson_gets_403_on_a_committee_they_do_not_chair(client, chair_setup):
    user, _, _, food = chair_setup
    client.force_login(user)
    response = client.get(detail_url(food))
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_chairperson_can_open_their_own_committees_detail(client, chair_setup):
    user, chair_person, ict, _ = chair_setup
    client.force_login(user)
    response = client.get(detail_url(ict))
    assert response.status_code == 200
    assert "Shan Malong" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", [groups.ICT, groups.BOARD])
def test_ict_and_board_see_all_twelve_committees(client, group_name):
    client.force_login(make_user(group_name, username=f"wide-{group_name}"))
    response = client.get(overview_url())
    assert response.status_code == 200
    assert len(response.context["cards"]) == 12


@pytest.mark.django_db
def test_a_treasurer_is_refused(client):
    client.force_login(make_user(groups.TREASURER))
    response = client.get(overview_url())
    assert response.status_code == 403


@pytest.mark.django_db
def test_an_anonymous_overview_request_is_refused(client):
    response = client.get(overview_url())
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_an_anonymous_detail_request_is_refused(client):
    sunshine = Committee.objects.get(code="sunshine")
    response = client.get(detail_url(sunshine))
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_drilling_into_a_committee_shows_its_roster_grouped_with_sub_functions(client):
    sunshine = Committee.objects.get(code="sunshine")
    transport = CommitteeFunction.objects.get(committee=sunshine, name="Transport")

    chair = Person.objects.create(last_name="Malong", first_name="Shan")
    co_chair = Person.objects.create(last_name="Reyes", first_name="Manex")
    driver = Person.objects.create(
        last_name="Cruz", first_name="Ana", mobile_number="09170000002",
    )
    CommitteeMembership.objects.create(
        committee=sunshine, person=chair, role=CommitteeRole.CHAIRPERSON, date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=sunshine, person=co_chair, role=CommitteeRole.CO_CHAIR, date_joined=JOINED,
    )
    CommitteeMembership.objects.create(
        committee=sunshine, person=driver, role=CommitteeRole.MEMBER, function=transport,
        date_joined=JOINED,
    )

    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(detail_url(sunshine))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Shan Malong" in body
    assert "Manex Reyes" in body
    assert "Ana Cruz" in body
    assert "Transport" in body
    assert "Chairperson" in body
    assert "Co-Chair" in body


@pytest.mark.django_db
def test_drilling_into_a_committee_shows_oversight_when_assigned(client):
    events = Committee.objects.get(code="events")
    board_position = Position.objects.get(code="board-member")
    overseer = Person.objects.create(last_name="Dela Cruz", first_name="Rico")
    Appointment.objects.create(person=overseer, position=board_position, start_date=JOINED)
    CommitteeMembership.objects.create(
        committee=events, person=overseer, role=CommitteeRole.OVERSIGHT, date_joined=JOINED,
    )

    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(detail_url(events))
    body = response.content.decode()

    assert "Rico Dela Cruz" in body
    assert "Board Oversight" in body
    assert "No Board Oversight assigned" not in body


@pytest.mark.django_db
def test_a_missing_committee_is_a_404(client):
    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(
        reverse("admin:committees_committeemembership_overview_detail", args=[999999])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_the_overview_and_changelist_link_to_each_other(client):
    client.force_login(make_user(groups.SECRETARIAT))

    overview_response = client.get(overview_url())
    assert reverse("admin:committees_committeemembership_changelist") in (
        overview_response.content.decode()
    )

    changelist_response = client.get(
        reverse("admin:committees_committeemembership_changelist")
    )
    assert overview_url() in changelist_response.content.decode()


@pytest.mark.django_db
def test_the_detail_page_links_to_add_a_member_prefilled_for_that_committee(client):
    sunshine = Committee.objects.get(code="sunshine")
    client.force_login(make_user(groups.SECRETARIAT))
    response = client.get(detail_url(sunshine))
    body = response.content.decode()
    add_url = reverse("admin:committees_committeemembership_add")
    assert f"{add_url}?committee={sunshine.pk}" in body


@pytest.mark.django_db
def test_adding_a_membership_from_the_detail_pages_add_link_still_works(client):
    sunshine = Committee.objects.get(code="sunshine")
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    client.force_login(make_user(groups.SECRETARIAT))

    add_url = reverse("admin:committees_committeemembership_add")
    prefilled = client.get(f"{add_url}?committee={sunshine.pk}")
    assert prefilled.status_code == 200

    response = client.post(
        add_url,
        {
            "committee": sunshine.pk,
            "person": person.pk,
            "function": "",
            "role": CommitteeRole.MEMBER,
            "date_joined": JOINED.isoformat(),
            "date_left": "",
            "_save": "Save",
        },
        follow=True,
    )
    assert response.status_code == 200
    assert CommitteeMembership.objects.filter(committee=sunshine, person=person).exists()


@pytest.mark.django_db
def test_an_accesslog_entry_is_written_for_the_overview_and_the_detail_page(client):
    sunshine = Committee.objects.get(code="sunshine")
    client.force_login(make_user(groups.SECRETARIAT))

    assert AccessLog.objects.count() == 0
    client.get(overview_url())
    assert AccessLog.objects.count() == 1
    assert AccessLog.objects.get().report == "committee overview"

    client.get(detail_url(sunshine))
    assert AccessLog.objects.count() == 2
    assert "Sunshine" in AccessLog.objects.latest("timestamp").report
