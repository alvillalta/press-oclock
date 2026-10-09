from functools import lru_cache
from supabase import Client, create_client
from app.core.config import settings


# Cachea el cliente Supabase del Storage, no la base de datos de db.py
@lru_cache
def get_supabase_client() -> Client:
    supabase_url = settings.SUPABASE_URL
    service_role_key = settings.SUPABASE_SERVICE_ROLE_KEY
    if not supabase_url or not service_role_key:
        # Pone el name como elemento de la lista missing_credentials si no existe una credential (supabase_url o service_role_key)
        missing_credentials = [
            name
            for credential, name in (
                (supabase_url, "SUPABASE_URL"),
                (service_role_key, "SUPABASE_SERVICE_ROLE_KEY"),
            )
            if not credential
        ]
        missing = " and ".join(missing_credentials)
        raise RuntimeError(f"Supabase client is not configured: {missing} must be set")

    # Crea un cliente a partir de la url de Supabase (HttpUrl -> str) sin la barra final y la service_role_key
    return create_client(str(supabase_url).rstrip("/"), service_role_key)
