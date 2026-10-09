import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict

from pgvector.sqlalchemy import Vector
from pydantic import EmailStr, StringConstraints
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import JSON, Field, Relationship, SQLModel

from app.core.config import settings


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# USER

class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Propiedades a recibir vía API
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Campos aceptados por el superusuario para poder editar un usuario (PATCH parcial)
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr = Field(unique=True, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    mails: list["Mail"] = Relationship(back_populates="user", cascade_delete=True)
    questions: list["Question"] = Relationship(
        back_populates="user", cascade_delete=True
    )


# Propiedades a devolver vía API
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# SOURCE

class Source(SQLModel, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    origin: str = Field(max_length=50, index=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    # Mail y Attachment son opcionales porque la Source solo puede ser de un tipo de manera que el otro no estará
    mail: Optional["Mail"] = Relationship(
        back_populates="source",
    )
    attachment: Optional["Attachment"] = Relationship(
        back_populates="source",
    )
    chunks: list["Chunk"] = Relationship(back_populates="source", cascade_delete=True)


class SourceCitation(SQLModel):
    source_id: uuid.UUID
    origin: str
    content: str = Field(
        min_length=1,
        max_length=800,
    )
    # Este diccionario se deja indicado porque es variable según mail, attachment, etc.
    details: dict[str, Any] = Field(default_factory=dict)


# MAIL

class MailBase(SQLModel):
    subject: str | None = Field(default=None, max_length=255)
    sender: EmailStr = Field(max_length=255)
    received_at: datetime = Field(sa_type=DateTime(timezone=True))


# Propiedades a recibir vía API
class MailCreate(MailBase):
    body: str | None = Field(default=None)


class Mail(MailBase, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    external_id: str | None = Field(default=None, max_length=255)
    source_id: uuid.UUID = Field(
        foreign_key="source.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    body: str | None = Field(default=None)
    user: User | None = Relationship(back_populates="mails")
    source: Source | None = Relationship(
        back_populates="mail",
    )
    attachments: list["Attachment"] = Relationship(
        back_populates="mail", cascade_delete=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_mail_user_external_id"),
    )


# Propiedades a devolver vía API
class MailPublic(MailBase):
    id: uuid.UUID
    user_id: uuid.UUID
    source_id: uuid.UUID
    created_at: datetime
    has_attachments: bool = False


class AttachmentPublic(SQLModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    extraction_status: str
    created_at: datetime


class MailResponse(MailPublic):
    body: str | None = None
    attachments: list[AttachmentPublic] = Field(default_factory=list)


# ATTACHMENT

class Attachment(SQLModel, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mail_id: uuid.UUID = Field(
        foreign_key="mail.id", nullable=False, ondelete="CASCADE"
    )
    source_id: uuid.UUID = Field(
        foreign_key="source.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    filename: str = Field(max_length=255)
    mime_type: str = Field(max_length=255)
    storage_path: str
    extraction: str | None = Field(default=None)
    # Estado de la futura extracción de texto (MarkItDown). En esta versión solo se
    # inicializa; ningún proceso lo modifica todavía.
    extraction_status: str = Field(default="pending", max_length=30)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    mail: Mail | None = Relationship(back_populates="attachments")
    source: Source | None = Relationship(
        back_populates="attachment",
    )


class MailStageCreate(MailBase):
    external_id: str = Field(min_length=1, max_length=255)
    body: str | None = Field(default=None)


class MailStage(SQLModel, table=True):
    """Temporary ingestion record kept until a staged mail is finalized."""

    __tablename__ = "mail_stage"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    external_id: str = Field(min_length=1, max_length=255)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    subject: str | None = Field(default=None, max_length=255)
    sender: EmailStr = Field(max_length=255)
    received_at: datetime = Field(sa_type=DateTime(timezone=True))
    body: str | None = Field(default=None)
    status: str = Field(default="receiving", max_length=30)
    total_size_bytes: int = Field(default=0, ge=0)
    mail_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="mail.id",
        ondelete="CASCADE",
        index=True,
    )
    result_summary: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    attachments: list["AttachmentStage"] = Relationship(
        back_populates="mail_stage", cascade_delete=True
    )
    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_mail_stage_user_external_id"),
    )


class AttachmentStage(SQLModel, table=True):
    """Temporary status and Storage path for one attachment upload."""

    __tablename__ = "attachment_stage"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mail_stage_id: uuid.UUID = Field(
        foreign_key="mail_stage.id", nullable=False, ondelete="CASCADE", index=True
    )
    external_id: str = Field(min_length=1, max_length=255)
    filename: str = Field(max_length=255)
    mime_type: str = Field(max_length=255)
    size_bytes: int = Field(default=0, ge=0)
    status: str = Field(default="pending", max_length=30)
    reason: str | None = Field(default=None, max_length=255)
    attempt_count: int = Field(default=0, ge=0)
    storage_path: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    mail_stage: MailStage | None = Relationship(back_populates="attachments")
    __table_args__ = (
        UniqueConstraint(
            "mail_stage_id", "external_id", name="uq_attachment_stage_mail_external_id"
        ),
    )


class MailStagePublic(SQLModel):
    ingestion_id: uuid.UUID | None = None
    external_id: str
    status: str
    mail_id: uuid.UUID | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)


class AttachmentStagePublic(SQLModel):
    external_id: str
    status: str
    reason: str | None = None
    attempt_count: int
    size_bytes: int


class AttachmentSignedUrl(SQLModel):
    url: str
    expires_in: int


class StorageCleanup(SQLModel, table=True):
    """Durable retry record for deleting an object from Supabase Storage."""

    __tablename__ = "storage_cleanup"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    storage_path: str = Field(unique=True, index=True)
    attempt_count: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


# CHUNK

class ChunkBase(SQLModel):
    content: str = Field(
        min_length=1,
        max_length=800,
    )
    position: int = Field(gt=0)


class ChunkCreate(ChunkBase):
    embedding: list[float] = Field(
        min_length=settings.EMBEDDING_DIMENSIONS,
        max_length=settings.EMBEDDING_DIMENSIONS,
        sa_type=Vector(settings.EMBEDDING_DIMENSIONS),
    )


class ChunkUpdate(SQLModel):
    content: str = Field(
        min_length=1,
        max_length=800,
    )


class Chunk(ChunkCreate, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_id: uuid.UUID = Field(
        foreign_key="source.id", nullable=False, ondelete="CASCADE"
    )
    source: Source | None = Relationship(back_populates="chunks")
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    __table_args__ = (
        # Condición de refuerzo para que en una misma source no pueda haber dos chunks ocupando la misma posición
        UniqueConstraint("source_id", "position", name="uq_chunk_source_position"),
    )


class AugmentedChunksGroup(TypedDict):
    source_id: uuid.UUID
    origin: str
    details: dict[str, Any]
    chunk_list: list[Chunk]


# QUESTION

# Propiedades a recibir vía API
QuestionBase = Annotated[
    str, StringConstraints(min_length=1, max_length=800, strip_whitespace=True)
]


QuestionEmbedding = Annotated[
    list[float],
    Field(
        min_length=settings.EMBEDDING_DIMENSIONS,
        max_length=settings.EMBEDDING_DIMENSIONS,
    ),
]


class QuestionCreate(SQLModel):
    question: QuestionBase
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)


class Question(QuestionCreate, table=True):
    """Database model"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    user: User | None = Relationship(back_populates="questions")
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


# Propiedades a devolver vía API
class QuestionPublic(QuestionCreate):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime


# OTROS

class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
