from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session, col, select

from app.core.logging import get_logger
from app.models import AugmentedChunksGroup, Mail

logger = get_logger(__name__)

SourceDetails = dict[str, Any]
# Callable define la firma para llamar a las funciones encargadas de los metadatos según origin
SourceDetailsLoader = Callable[[Session, list[UUID]], dict[UUID, SourceDetails]]


def _load_mail_details(
    session: Session, source_ids: list[UUID]
) -> dict[UUID, SourceDetails]:  # diccionario con CLAVE: source_id -> VALOR: SourceDetails
    query = (
        select(Mail)
        .where(col(Mail.source_id).in_(source_ids))
    )
    mails = list(session.exec(query).all())
    return {
        mail.source_id: {
            "mail_id": mail.id,
            "subject": mail.subject,
            "sender": str(mail.sender),
            "received_at": mail.received_at,
        }
        for mail in mails
    }


# Diccionario de mapeo
SOURCE_DETAILS_LOADERS: dict[str, SourceDetailsLoader] = {
    "mail": _load_mail_details,
}


def get_metadata(
    session: Session,
    source_chunks_groups: list[AugmentedChunksGroup],
) -> list[AugmentedChunksGroup]:
    """
    Carga los metadatos específicos de las fuentes de los grupos de chunks previamente seleccionados.
    """
    logger.info("Loading specific metadata from already selected sources")

    # Crea un diccionario con CLAVE: origin -> VALOR: lista de source_id que pertenecen a ese origin
    source_ids_by_origin: dict[str, list[UUID]] = {}

    for group in source_chunks_groups:
        origin = group["origin"]

        if origin not in source_ids_by_origin:
            source_ids_by_origin[origin] = []

        source_ids_by_origin[origin].append(group["source_id"])

    # Crea un diccionario con CLAVE: source_id -> VALOR: instancia de metadatos específicos de la fuente según origen
    details_by_source_id: dict[UUID, SourceDetails] = {}

    # Bucle para recorrer las parejas CLAVE-VALOR gracias al método items()
    for origin, source_ids in source_ids_by_origin.items():
        # Se envia el origin a un diccionario de mapeo para poder invocar a su función asociada
        loader = SOURCE_DETAILS_LOADERS.get(origin)
        if loader is not None:
            # update() es como un append() pero para parejas clave-valor de un diccionario
            details_by_source_id.update(loader(session, source_ids))

    # Para cada grupo crea un diccionario nuevo que conserva sus campos originales y añade el diccionario específico de details. Si no encontró metadatos para ese ID, usa {}
    return [
        {
            **group,
            "details": details_by_source_id.get(group["source_id"], {}),
        }
        for group in source_chunks_groups
    ]


class MetadataService:
    """Carga los metadatos de las fuentes de los chunks"""

    def load_source_details(
            self,
            session: Session,
            augmented_chunks: list[AugmentedChunksGroup]
        ) -> list[AugmentedChunksGroup]:
            return get_metadata(session, augmented_chunks)


