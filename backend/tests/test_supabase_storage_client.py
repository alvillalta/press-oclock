from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.integrations import supabase_storage_client


@pytest.fixture(autouse=True)
def clear_supabase_storage_client_cache():
    supabase_storage_client.get_supabase_storage_client.cache_clear()
    yield
    supabase_storage_client.get_supabase_storage_client.cache_clear()


def test_get_supabase_storage_client_caches_one_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://supabase.example/")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "service-role-key")
    client = object()
    create_client = Mock(return_value=client)
    monkeypatch.setattr(supabase_storage_client, "create_client", create_client)

    first_client = supabase_storage_client.get_supabase_storage_client()
    second_client = supabase_storage_client.get_supabase_storage_client()

    assert first_client is client
    assert second_client is client
    create_client.assert_called_once_with(
        "https://supabase.example", "service-role-key"
    )


@pytest.mark.parametrize(
    ("missing_setting", "missing_name"),
    [
        ("SUPABASE_STORAGE_URL", "SUPABASE_STORAGE_URL"),
        ("SUPABASE_STORAGE_KEY", "SUPABASE_STORAGE_KEY"),
    ],
)
def test_get_supabase_storage_client_reports_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
    missing_setting: str,
    missing_name: str,
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://supabase.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "service-role-key")
    monkeypatch.setattr(settings, missing_setting, None)

    with pytest.raises(RuntimeError, match=missing_name):
        supabase_storage_client.get_supabase_storage_client()
