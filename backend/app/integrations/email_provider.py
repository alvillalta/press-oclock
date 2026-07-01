from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session

from app.models import Message


def detect_provider(email: str) -> str | None:
    try:
        domain = email.split("@", 1)[1].lower()
    except IndexError:
        return None

    if domain in ["gmail.com"]:
        return "gmail"

    if domain in ["outlook.com", "hotmail.com", "live.com"]:
        return "outlook"

    if domain in ["icloud.com", "me.com"]:
        return "icloud"

    if domain in ["yahoo.com"]:
        return "yahoo"

    return None


class BaseEmailProvider:
    provider_name = "unknown"

    def __init__(self, session: Session) -> None:
        self.session = session

    def sync(self, user_id: UUID, email: str) -> Message:
        return Message(
            message=f"Sync started for {email} using provider {self.provider_name}."
        )


class GmailProvider(BaseEmailProvider):
    provider_name = "gmail"


class OutlookProvider(BaseEmailProvider):
    provider_name = "outlook"


class ICloudProvider(BaseEmailProvider):
    provider_name = "icloud"


class YahooProvider(BaseEmailProvider):
    provider_name = "yahoo"


class EmailProvider:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_provider(self, user_id: UUID, email: str) -> Message:
        provider_name = detect_provider(email)
        if provider_name is None:
            raise HTTPException(
                status_code=400,
                detail="No se pudo detectar automáticamente el proveedor de correo y no lo soportamos",
            )

        if provider_name == "gmail":
            return GmailProvider(self.session).sync(user_id=user_id, email=email)

        if provider_name == "outlook":
            return OutlookProvider(self.session).sync(user_id=user_id, email=email)

        if provider_name == "icloud":
            return ICloudProvider(self.session).sync(user_id=user_id, email=email)

        if provider_name == "yahoo":
            return YahooProvider(self.session).sync(user_id=user_id, email=email)

        raise HTTPException(
            status_code=400,
            detail=f"Proveedor de correo '{provider_name}' no soportado",
        )
