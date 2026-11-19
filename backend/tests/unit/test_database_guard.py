import pytest
from sqlalchemy import make_url

from tests.utils.database_guard import ensure_test_database


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@localhost:5433/press_oclock_test",
        "postgresql+psycopg://user:password@127.0.0.1:5433/press_oclock_test",
    ],
)
def test_ensure_test_database_accepts_local_test_database(database_url: str) -> None:
    ensure_test_database(make_url(database_url))


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@localhost:5432/postgres",
        "postgresql+psycopg://user:password@db.example.supabase.co:5432/postgres",
        "postgresql+psycopg://user:password@db.example.supabase.co:5432/press_oclock_test",
    ],
)
def test_ensure_test_database_aborts_on_any_other_database(database_url: str) -> None:
    with pytest.raises(pytest.exit.Exception):
        ensure_test_database(make_url(database_url))


def test_ensure_test_database_hides_credentials_when_aborting() -> None:
    database_url = (
        "postgresql+psycopg://real-user:real-password@db.example.com/postgres"
    )

    with pytest.raises(pytest.exit.Exception) as aborted:
        ensure_test_database(make_url(database_url))

    assert "real-user" not in str(aborted.value)
    assert "real-password" not in str(aborted.value)
