import pytest
from django.db import IntegrityError

from committees.models import Committee, CommitteeFunction


@pytest.mark.django_db
def test_twelve_committees_are_seeded():
    assert Committee.objects.count() == 12


@pytest.mark.django_db
def test_eleven_committees_appear_on_the_profiling_form():
    """Spec D7: Grievance and Reconciliation is appointed, not self-selected."""
    assert Committee.objects.filter(is_self_selectable=True).count() == 11
    grievance = Committee.objects.get(code="grievance-and-reconciliation")
    assert grievance.is_self_selectable is False


@pytest.mark.django_db
def test_sunshine_has_its_three_functions():
    sunshine = Committee.objects.get(code="sunshine")
    names = set(sunshine.functions.values_list("name", flat=True))
    assert names == {"Ushering and Marshall", "Transport", "Benevolence"}


@pytest.mark.django_db
def test_function_names_are_unique_within_a_committee():
    sunshine = Committee.objects.get(code="sunshine")
    with pytest.raises(IntegrityError):
        CommitteeFunction.objects.create(committee=sunshine, name="Transport")
