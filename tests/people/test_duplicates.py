"""Side-by-side duplicate review, added 2026-08-24.

Two real cases in one week prompted it: a child written with a middle name
on one parent's form and without it on the other's, and a committee
chairperson seeded from the Board minutes who then filled in her own
profiling form. The second is structural, not bad luck -- every officer
seeded from the minutes will eventually submit a form.

The tests below are mostly about the thing that makes this dangerous: the
record holding MORE is not necessarily the record that is RIGHT, and the
seeded chairperson looks emptier than her own form while being the row that
carries her committee role.

All names below are fabricated. Real member data lives in `form images/`
and is never used in fixtures or tests.
"""

import datetime as dt

import pytest
from django.utils import timezone
from django.contrib.auth.models import Group, User
from django.urls import reverse

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.duplicates import (
    completeness,
    compare,
    find_duplicate_pairs,
    merge_into,
)
from people.models import (
    Household,
    HouseholdMember,
    HouseholdRole,
    MembershipStatus,
    Person,
)

# timezone.localdate(), not dt.date.today(): the code computes every
# window against TIME_ZONE (Asia/Manila) while date.today() reads the
# machine's own clock. Around midnight Manila the two are a day apart,
# and a test saying "a birthday two days from now" then builds a date
# the code does not agree is two days away. A suite that fails once a
# day at a particular hour teaches whoever inherits it to re-run until
# green (R6).
TODAY = timezone.localdate()


def duplicates_url():
    return reverse("admin:people_person_duplicates")


def make_user(username, group_name):
    user = User.objects.create_user(username, password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


@pytest.fixture
def seeded_chair(db):
    """What seed_officers writes from the Board minutes: a name, a nickname
    and a committee role. No birthdate, no contact, no form."""
    person = Person.objects.create(
        last_name="Abaigar",
        first_name="Sonia",
        nickname="Sony",
        membership_status=MembershipStatus.MEMBER,
    )
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="food"),
        person=person,
        role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY - dt.timedelta(days=60),
    )
    return person


@pytest.fixture
def her_own_form(db):
    """What her profiling form creates months later: everything except the
    committee role, because the form has no way to say "I chair this"."""
    person = Person.objects.create(
        last_name="Abaigar",
        first_name="Sonia",
        middle_name="Bayatin",
        date_of_birth=dt.date(1979, 7, 2),
        home_address="14 Fictional Street, La Trinidad",
        mobile_number="09181234567",
        email="sonia@example.com",
        civil_status="MARRIED",
        date_filed=TODAY - dt.timedelta(days=2),
        membership_status=MembershipStatus.MEMBER,
    )
    CommitteeMembership.objects.create(
        committee=Committee.objects.get(code="food"),
        person=person,
        role=CommitteeRole.MEMBER,
        date_joined=TODAY - dt.timedelta(days=2),
    )
    return person


# -- finding -----------------------------------------------------------


@pytest.mark.django_db
def test_the_seeded_officer_and_her_own_form_are_found_as_a_pair(seeded_chair, her_own_form):
    pairs = find_duplicate_pairs()

    assert len(pairs) == 1
    assert {pairs[0].left.pk, pairs[0].right.pk} == {seeded_chair.pk, her_own_form.pk}


@pytest.mark.django_db
def test_a_middle_name_on_only_one_side_still_matches(db):
    """How the Abaigar pair was created in the first place."""
    Person.objects.create(last_name="Abaigar", first_name="Rhyzel")
    Person.objects.create(last_name="Abaigar", first_name="Rhyzel", middle_name="Bayatin")

    assert len(find_duplicate_pairs()) == 1


@pytest.mark.django_db
def test_two_different_people_sharing_a_surname_are_not_a_pair(db):
    Person.objects.create(last_name="Abaigar", first_name="Sonia")
    Person.objects.create(last_name="Abaigar", first_name="Rhyzel")

    assert find_duplicate_pairs() == []


@pytest.mark.django_db
def test_matching_does_not_require_a_birthdate(db):
    """Half the register has none and the seeded officers have none by
    construction, so requiring one would miss exactly the duplicates that
    actually occur."""
    Person.objects.create(last_name="Abaigar", first_name="Sonia")
    Person.objects.create(last_name="Abaigar", first_name="Sonia")

    assert len(find_duplicate_pairs()) == 1


# -- comparing ---------------------------------------------------------


@pytest.mark.django_db
def test_the_fuller_record_is_named_but_only_as_a_count(seeded_chair, her_own_form):
    pair = compare(seeded_chair, her_own_form)

    assert completeness(her_own_form) > completeness(seeded_chair)
    assert pair.fuller == her_own_form


@pytest.mark.django_db
def test_records_holding_the_same_amount_name_neither(db):
    left = Person.objects.create(last_name="Abaigar", first_name="Sonia", nickname="A")
    right = Person.objects.create(last_name="Abaigar", first_name="Sonia", nickname="B")

    assert compare(left, right).fuller is None


@pytest.mark.django_db
def test_a_disagreement_is_reported_separately_from_a_gap(db):
    """A field only one record has is a gap. A field both have, differing,
    means one of them is wrong -- which is the reviewer's real work."""
    left = Person.objects.create(
        last_name="Abaigar", first_name="Sonia", mobile_number="09181111111"
    )
    right = Person.objects.create(
        last_name="Abaigar", first_name="Sonia",
        mobile_number="09182222222", email="sonia@example.com",
    )

    pair = compare(left, right)
    conflicting = [field.label for field in pair.conflicts]

    assert "Mobile Number" in conflicting
    assert "Email" not in conflicting  # only one side has it — a gap, not a clash


@pytest.mark.django_db
def test_what_each_record_would_take_with_it_is_counted(seeded_chair, her_own_form):
    """The commonest wrong choice is deleting the seeded chairperson, who
    looks emptier while carrying the committee role."""
    pair = compare(seeded_chair, her_own_form)

    assert pair.left_attachments["committees"] == 1
    assert pair.right_attachments["committees"] == 1


# -- merging -----------------------------------------------------------


@pytest.mark.django_db
def test_merging_keeps_the_appointed_role_over_a_plain_membership(seeded_chair, her_own_form):
    """The case this exists for. Keeping her fuller form record must not
    quietly demote her from Chairperson of Food to Member."""
    merge_into(keep=her_own_form, remove=seeded_chair)

    assert not Person.objects.filter(pk=seeded_chair.pk).exists()
    role = CommitteeMembership.objects.get(person=her_own_form, committee__code="food")
    assert role.role == CommitteeRole.CHAIRPERSON


@pytest.mark.django_db
def test_merging_moves_households_and_scans_across(db):
    keep = Person.objects.create(last_name="Abaigar", first_name="Sonia")
    remove = Person.objects.create(last_name="Abaigar", first_name="Sonia")
    household = Household.objects.create(name="Abaigar Family")
    HouseholdMember.objects.create(
        household=household, person=remove, role=HouseholdRole.HEAD
    )

    moved = merge_into(keep=keep, remove=remove)

    assert moved["households"] == 1
    assert HouseholdMember.objects.get(household=household).person == keep


@pytest.mark.django_db
def test_merging_never_copies_field_values_between_the_two(db):
    """Deciding whose birthdate is right is the reviewer's judgement. A
    merge that quietly overwrote the kept record would be making it."""
    keep = Person.objects.create(
        last_name="Abaigar", first_name="Sonia", date_of_birth=dt.date(1979, 7, 2)
    )
    remove = Person.objects.create(
        last_name="Abaigar", first_name="Sonia",
        date_of_birth=dt.date(1980, 1, 1), email="sonia@example.com",
    )

    merge_into(keep=keep, remove=remove)

    keep.refresh_from_db()
    assert keep.date_of_birth == dt.date(1979, 7, 2)
    assert keep.email == ""


@pytest.mark.django_db
def test_a_guardian_link_follows_the_surviving_record(db):
    keep = Person.objects.create(last_name="Abaigar", first_name="Sonia")
    remove = Person.objects.create(last_name="Abaigar", first_name="Sonia")
    child = Person.objects.create(
        last_name="Abaigar", first_name="Rhyzel",
        membership_status=MembershipStatus.CHILD, guardian=remove,
    )

    merge_into(keep=keep, remove=remove)

    child.refresh_from_db()
    assert child.guardian == keep


# -- the screen --------------------------------------------------------


@pytest.mark.django_db
def test_ict_can_open_the_screen_and_sees_both_records(client, seeded_chair, her_own_form):
    client.force_login(make_user("ict", groups.ICT))

    body = client.get(duplicates_url()).content.decode()

    assert "Possible duplicates" in body
    assert "Sonia" in body
    assert "09181234567" in body


@pytest.mark.django_db
def test_the_secretariat_cannot_reach_it(client, seeded_chair, her_own_form):
    """Deleting a person is ICT's alone (spec 4). The Secretariat manages
    records; it does not destroy them."""
    client.force_login(make_user("sec", groups.SECRETARIAT))

    assert client.get(duplicates_url()).status_code == 403


@pytest.mark.django_db
def test_a_chairperson_cannot_reach_it(client):
    client.force_login(make_user("chair", groups.CHAIRPERSON))

    assert client.get(duplicates_url()).status_code == 403


@pytest.mark.django_db
def test_posting_a_choice_merges_and_reports_what_moved(client, seeded_chair, her_own_form):
    client.force_login(make_user("ict", groups.ICT))

    response = client.post(
        duplicates_url(),
        {"keep": her_own_form.pk, "remove": seeded_chair.pk},
        follow=True,
    )

    assert not Person.objects.filter(pk=seeded_chair.pk).exists()
    assert "Kept Sonia Bayatin Abaigar" in response.content.decode()


@pytest.mark.django_db
def test_an_empty_register_says_so_rather_than_rendering_nothing(client):
    client.force_login(make_user("ict", groups.ICT))

    body = client.get(duplicates_url()).content.decode()

    assert "no two people and no two households" in body


@pytest.mark.django_db
def test_a_nonsense_post_changes_nothing(client, seeded_chair, her_own_form):
    client.force_login(make_user("ict", groups.ICT))

    client.post(duplicates_url(), {"keep": seeded_chair.pk, "remove": seeded_chair.pk})

    assert Person.objects.filter(pk=seeded_chair.pk).exists()
    assert Person.objects.filter(pk=her_own_form.pk).exists()


# -- near-miss spellings (2026-08-24) ----------------------------------


@pytest.mark.django_db
def test_a_middle_initial_and_the_spelled_out_name_are_one_pair(db):
    """The Til-Adan case: the parent's form gave "A.", the child's own form
    gave "Angel". These are one child written twice."""
    Person.objects.create(
        last_name="Til-Adan", first_name="Johnson", middle_name="A."
    )
    Person.objects.create(
        last_name="Til-Adan", first_name="Johnson", middle_name="Angel"
    )

    pairs = find_duplicate_pairs()

    assert len(pairs) == 1
    assert "compatible given name" in pairs[0].reason


@pytest.mark.django_db
def test_a_first_name_one_typo_apart_is_shown_but_marked_weaker(db):
    """"Jonhmar" and "Johnmar" -- two letters swapped copying a name off a
    form. Never linked automatically; a person has to look."""
    Person.objects.create(last_name="Til-Adan", first_name="Jonhmar")
    Person.objects.create(last_name="Til-Adan", first_name="Johnmar")

    pairs = find_duplicate_pairs()

    assert len(pairs) == 1
    assert "differ by one letter" in pairs[0].reason


@pytest.mark.django_db
def test_two_genuinely_different_short_names_are_not_paired(db):
    """Below four letters a single edit is most of the word, and Ana and
    Ann are two real names."""
    Person.objects.create(last_name="Til-Adan", first_name="Ana")
    Person.objects.create(last_name="Til-Adan", first_name="Ann")

    assert find_duplicate_pairs() == []


@pytest.mark.django_db
def test_two_unrelated_names_are_not_paired(db):
    Person.objects.create(last_name="Til-Adan", first_name="Johnson")
    Person.objects.create(last_name="Til-Adan", first_name="Gemma")

    assert find_duplicate_pairs() == []


@pytest.mark.django_db
def test_the_reason_is_shown_on_the_screen(client, db):
    Person.objects.create(last_name="Til-Adan", first_name="Jonhmar")
    Person.objects.create(last_name="Til-Adan", first_name="Johnmar")
    client.force_login(make_user("ict", groups.ICT))

    body = client.get(duplicates_url()).content.decode()

    assert "differ by one letter" in body
