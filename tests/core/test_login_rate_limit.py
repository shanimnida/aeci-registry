from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

from core.login import LOCKED_MESSAGE, _key
from core.models import LoginAttempt


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def login_settings(settings):
    settings.LOGIN_ACCOUNT_FAILURE_LIMIT = 3
    settings.LOGIN_IP_FAILURE_LIMIT = 6
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def login(client, username="officer", password="wrong", ip="192.0.2.1", **headers):
    return client.post("/admin/login/", {"username": username, "password": password},
                       REMOTE_ADDR=ip, **headers)


@pytest.fixture
def officer():
    return User.objects.create_user("officer", password="valid-password", is_staff=True)


def test_account_lockout_applies_across_ips_and_commits_failures(client, officer):
    for n in range(3):
        assert login(client, ip=f"192.0.2.{n + 1}").status_code == 200
    assert LoginAttempt.objects.get(key=_key("account", "officer")).failures == 3
    response = login(client, password="valid-password", ip="192.0.2.99")
    assert LOCKED_MESSAGE in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_ip_lockout_applies_across_usernames_and_ignores_spoofed_headers(client):
    for n in range(6):
        login(client, username=f"missing{n}", HTTP_X_FORWARDED_FOR=f"198.51.100.{n}")
    response = login(client, username="another", HTTP_X_FORWARDED_FOR="203.0.113.8")
    assert LOCKED_MESSAGE in response.content.decode()


def test_blocked_attempt_does_not_extend_cooldown_and_expiry_allows_login(client, officer):
    for _ in range(3):
        login(client)
    bucket = LoginAttempt.objects.get(key=_key("account", "officer"))
    locked_until = bucket.locked_until
    login(client)
    bucket.refresh_from_db()
    assert bucket.locked_until == locked_until
    LoginAttempt.objects.filter(pk=bucket.pk).update(
        locked_until=timezone.now() - timedelta(seconds=1)
    )
    assert login(client, password="valid-password").status_code == 302


def test_success_resets_account_but_preserves_ip_failures(client, officer):
    login(client)
    assert login(client, password="valid-password").status_code == 302
    assert LoginAttempt.objects.get(key=_key("account", "officer")).failures == 0
    assert LoginAttempt.objects.get(key=_key("ip", "192.0.2.1")).failures == 1
    # Existing sessions can keep using the site even if the IP later locks.
    LoginAttempt.objects.filter(key=_key("ip", "192.0.2.1")).update(
        locked_until=timezone.now() + timedelta(minutes=15)
    )
    assert client.get("/admin/").status_code == 200


@pytest.mark.parametrize("active,staff", [(False, True), (True, False)])
def test_inactive_and_nonstaff_accounts_are_throttled(client, active, staff):
    User.objects.create_user("officer", password="valid-password", is_active=active, is_staff=staff)
    for _ in range(3):
        login(client, password="valid-password")
    assert LOCKED_MESSAGE in login(client, password="valid-password").content.decode()


def test_only_old_login_counters_are_pruned():
    old = LoginAttempt.objects.create(key="old", window_started_at=timezone.now())
    recent = LoginAttempt.objects.create(key="recent", window_started_at=timezone.now())
    LoginAttempt.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
    call_command("prune_login_attempts")
    assert not LoginAttempt.objects.filter(pk=old.pk).exists()
    assert LoginAttempt.objects.filter(pk=recent.pk).exists()


def test_login_keys_do_not_store_plain_usernames_or_ips(client):
    login(client)
    keys = list(LoginAttempt.objects.values_list("key", flat=True))
    assert len(keys) == 2
    assert all("officer" not in key and "192.0.2.1" not in key for key in keys)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_overlapping_failures_cannot_bypass_account_limit():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connections
    from django.test import Client

    barrier = Barrier(5)
    def attempt(n):
        try:
            barrier.wait(timeout=10)
            return login(Client(), ip=f"192.0.2.{n + 1}").status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert list(pool.map(attempt, range(5))) == [200] * 5
    bucket = LoginAttempt.objects.get(key=_key("account", "officer"))
    assert bucket.failures == 3
    assert bucket.locked_until > timezone.now()
