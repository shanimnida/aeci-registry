import pytest

from scripts.verify_backup_restore import restore_target


@pytest.mark.parametrize("url", [
    "postgres://user:password@production.example.com/aegis_restore_check",
    "postgres://user:password@localhost/aegis_production",
    "postgres://user:password@localhost/postgres",
    "https://localhost/aegis_restore_check",
])
def test_restore_check_refuses_production_or_unexpected_targets(url):
    with pytest.raises(ValueError, match="local disposable"):
        restore_target(url)


def test_restore_check_accepts_only_named_local_scratch_database():
    assert restore_target("postgres://postgres@127.0.0.1:55433/aegis_restore_check").port == 55433
