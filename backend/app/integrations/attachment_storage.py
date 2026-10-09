import asyncio
from typing import Any
from urllib.parse import quote, urljoin

from supabase import Client

from app.core.config import settings
from app.integrations.supabase_client import get_supabase_client


class AttachmentStorage:
    """Async adapter around the synchronous Supabase Storage client."""

    def __init__(self, client: Client | None = None) -> None:
        self._client = client
        self.expires_in = 300

    def _get_client(self) -> Client:
        if self._client is not None:
            return self._client
        self._client = get_supabase_client()
        return self._client

    def _bucket(self) -> Any:
        # Trae la instancia del bucket del Storage de Supabase
        return self._get_client().storage.from_(settings.SUPABASE_STORAGE_BUCKET)

    # No lleva return porque simplemente propaga la excepción a mail_service.py si falla
    async def upload(self, path: str, content: bytes, mime_type: str) -> None:
        bucket = self._bucket()
        await asyncio.to_thread(  # Separa operaciones asíncronas bloqueantes durante la ejecución en hilos separados (subir una imagen >3s) para aceptar concurrencia
            bucket.upload,  # bucket.upload: instrucción para Supabase
            path=path,
            file=content,
            file_options={"content-type": mime_type, "upsert": "true"},  # upsert reemplaza el archivo si ya existía en esa ruta
        )

    async def remove(self, paths: list[str]) -> None:
        if not paths:
            return
        bucket = self._bucket()
        await asyncio.to_thread(bucket.remove, paths)  # bucket.remove: instrucción para Supabase

    async def download(self, path: str) -> bytes:
        bucket = self._bucket()
        content = await asyncio.to_thread(bucket.download, path)  # bucket.download: instrucción para Supabase
        return bytes(content)  # Asegura el archivo en bytes de forma defensiva

    # Genera una URL temporal para acceder al archivo
    async def create_signed_url(
        self, path: str, download_filename: str | None = None  # Asegura el nombre del archivo de descarga por si Supabase le cambiase el nombre internamente
    ) -> str:
        bucket = self._bucket()
        options: dict[str, str] = {}
        if download_filename:
            options["download"] = download_filename
        response = await asyncio.to_thread(
            bucket.create_signed_url,  # bucket.create_signed_url: instrucción para Supabase
            path,
            self.expires_in,
            options=options or None,
        )
        # Se prueba con varias claves porque Supabase puede cambiarlas en algún momento
        signed_url = response.get("signedURL") or response.get("signedUrl") or response.get("signed_url")
        if not isinstance(signed_url, str) or not signed_url:
            raise RuntimeError("Supabase Storage did not return a signed URL")
        # Completa la URL si viene como ruta relativa
        if signed_url.startswith("/"):
            base_url = str(settings.SUPABASE_URL).rstrip("/")
            return urljoin(f"{base_url}/", signed_url.lstrip("/"))
        # Añade el nombre del archivo si falta en la signed_url
        if download_filename and "download=" not in signed_url:
            separator = "&" if "?" in signed_url else "?"
            signed_url = f"{signed_url}{separator}download={quote(download_filename)}"
        return signed_url
