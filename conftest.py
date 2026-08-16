import pytest
from django.contrib.auth.models import User


@pytest.fixture
def ict_user(db):
    return User.objects.create_user("ict", password="x", is_staff=True)
