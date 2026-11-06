from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain.agents import AgentState
from sqlmodel import Session

from app.models import AugmentedChunksGroup, Chunk, SourceCitation


@dataclass(frozen=True)  # frozen=True impide reasignar los atributos de la instancia desde el momento en el que se crea
class RagAgentContext:
    session: Session
    user_id: UUID


class RagAgentState(AgentState[Any]):
    similar_chunks: list[Chunk]
    augmented_chunk_groups: list[AugmentedChunksGroup]
    search_count: int
    search_error_code: str | None
    search_error_message: str | None


@dataclass
class RagAgentResponse:
    answer: str
    citations: list[SourceCitation]
