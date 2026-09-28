from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlmodel import Session, col, select

from app.core.logging import get_logger
from app.models import AugmentedChunksGroup, Chunk, Mail, SourceCitation

logger = get_logger(__name__)

SourceDetails = dict[str, Any]
# Define la firma que para llamar a las funciones encargadas de los metadatos según origin
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


def load_source_details(
    *,
    session: Session,
    source_chunks_groups: list[AugmentedChunksGroup],
) -> list[AugmentedChunksGroup]:
    """
    Carga los metadatos específicos de los ya seleccionados grupos de una fuente.
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


def get_sources(
    similar_chunks: list[Chunk],
    augmented_chunks: list[AugmentedChunksGroup],
) -> list[SourceCitation]:
    """
    Crea citas utilizando los chunks originales recuperados y los metadatos asociados a la fuente.
    """
    logger.info("Creating source citations")

    # Crea un diccionario con CLAVE: source_id -> VALOR: instancia de grupo de chunks
    metadata_by_source_id = {
        group["source_id"]: group for group in augmented_chunks
    }
    sources: list[SourceCitation] = []

    for chunk in similar_chunks:
        # Por cada chunk original recupera la instancia de grupo de chunks
        source_chunks_group = metadata_by_source_id.get(chunk.source_id)
        if source_chunks_group is None:
            continue

        sources.append(
            SourceCitation(
                source_id=chunk.source_id,
                origin=source_chunks_group["origin"],
                content=chunk.content,
                details=source_chunks_group["details"],
            )
        )

    return sources
