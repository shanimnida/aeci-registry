import pytest
from django.contrib.auth.models import User


@pytest.fixture
def ict_user(db):
    return User.objects.create_user("ict", password="x", is_staff=True)


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    """Let admin pages render without a collectstatic manifest.

    Production serves static files through whitenoise's manifest storage,
    which raises unless collectstatic has run. The test suite should not
    depend on a build step.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
