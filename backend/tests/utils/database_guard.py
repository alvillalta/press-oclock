import pytest
from sqlalchemy import URL

LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1"}
TEST_DATABASE_SUFFIX = "_test"


def ensure_test_database(url: URL) -> None:
    database_name = url.database or ""
    is_local_host = url.host in LOCAL_DATABASE_HOSTS
    if is_local_host and database_name.endswith(TEST_DATABASE_SUFFIX):
        return
    pytest.exit(
        "Tests aborted: expected a local database ending in "
        f"'{TEST_DATABASE_SUFFIX}', got host={url.host!r} database={database_name!r}.",
        returncode=1,
    )
