import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict

from app.core.config import settings
from pgvector.sqlalchemy import Vector
from pydantic import EmailStr, StringConstraints
from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlmodel import JSON, Field, Relationship, SQLModel




def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Fields accepted by the superuser update endpoint. Email is required, while omitted fields retain their current values.
class UserUpdate(UserBase):
    email: EmailStr = Field(unique=True, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr = Field(unique=True, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    mails: list["Mail"] = Relationship(back_populates="user", cascade_delete=True)
    questions: list["Question"] = Relationship(back_populates="user", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Mail shared properties
class MailBase(SQLModel):
    subject: str | None = Field(default=None, max_length=255)
    sender: EmailStr = Field(max_length=255)
    received_at: datetime = Field(sa_type=DateTime(timezone=True))


class Source(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    origin: str = Field(max_length=50, index=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    mail: Optional["Mail"] = Relationship(  # noqa: UP045
        back_populates="source",
    )
    attachment: Optional["Attachment"] = Relationship(  # noqa: UP045
        back_populates="source",
    )
    chunks: list["Chunk"] = Relationship(back_populates="source", cascade_delete=True)
    __table_args__ = (
        Index("ix_source_user_origin", "user_id", "origin"),
    )


# External Mail model
class MailData(MailBase):
    body: str | None = Field(default=None)


# Properties to receive on mail creation
class MailCreate(MailBase):
    body: str | None = Field(default=None)


# Mail database model
class Mail(MailBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
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


class MailPublic(MailBase):
    id: uuid.UUID
    user_id: uuid.UUID
    source_id: uuid.UUID
    created_at: datetime


class MailResponse(MailPublic):
    body: str | None = None


class Attachment(SQLModel, table=True):
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
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    mail: Mail | None = Relationship(back_populates="attachments")
    source: Source | None = Relationship(
        back_populates="attachment",
    )

# Chunk shared properties
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


# Properties to receive on chunk update
class ChunkUpdate(SQLModel):
    content: str = Field(
        min_length=1,
        max_length=800,
    )


# Chunk database model
class Chunk(ChunkCreate, table=True):
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
        UniqueConstraint("source_id", "position", name="uq_chunk_source_position"),
    )


class AugmentedChunksGroup(TypedDict):
    source_id: uuid.UUID
    origin: str
    details: dict[str, Any]
    chunk_list: list[Chunk]


# Question shared properties
QuestionBase = Annotated[
        str,
        StringConstraints(min_length=1, max_length=800, strip_whitespace=True)
]


QuestionEmbedding = Annotated[
    list[float],
    Field(min_length=settings.EMBEDDING_DIMENSIONS, max_length=settings.EMBEDDING_DIMENSIONS),
]


class SourceCitation(SQLModel):
    source_id: uuid.UUID
    origin: str
    content: str = Field(
        min_length=1,
        max_length=800,
    )
    details: dict[str, Any] = Field(default_factory=dict)


class QuestionCreate(SQLModel):
    question: QuestionBase
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON)


# Question database model
class Question(QuestionCreate, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    user: User | None = Relationship(back_populates="questions")
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )

# Generic message
class Message(SQLModel):
    message: str

"""
# Login request payload
class LoginRequest(SQLModel):
    email: EmailStr
    password: str
 """

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
