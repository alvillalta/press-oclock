import uuid
from typing import Annotated, Any, TypeAlias, TypedDict
from datetime import datetime, timezone

from pydantic import EmailStr, StringConstraints
from sqlalchemy import DateTime
from sqlmodel import JSON, Field, Relationship, SQLModel
from pgvector.sqlalchemy import Vector


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


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr = Field(unique=True, max_length=255)
    password: str = Field(min_length=8, max_length=128)


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
    date: datetime = Field(sa_type=DateTime(timezone=True))


# External Mail model
class MailData(MailBase):
    body: str | None = Field(default=None)


# Properties to receive on mail creation
class MailCreate(MailBase):
    pass


# Mail database model
class Mail(MailBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    user: User | None = Relationship(back_populates="mails")
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    chunks: list["Chunk"] = Relationship(back_populates="mail", cascade_delete=True)


# Chunk shared properties
class ChunkBase(SQLModel):
    chunk_text: str = Field(
        min_length=1, 
        max_length=800, 
    )
    chunk_index: int = Field(gt=0)


class ChunkCreate(ChunkBase):
    embedding: list[float] = Field(sa_type=Vector(1536))


# Properties to receive on chunk update
class ChunkUpdate(SQLModel):
    chunk_text: str = Field(
        min_length=1, 
        max_length=800, 
    )


# Chunk database model
class Chunk(ChunkCreate, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mail_id: uuid.UUID = Field(
        foreign_key="mail.id", nullable=False, ondelete="CASCADE"
    )
    mail: Mail | None = Relationship(back_populates="chunks")
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class AugmentedMailChunksGroup(TypedDict):
    mail_id: uuid.UUID
    subject: str | None
    sender: EmailStr
    date: datetime
    chunk_list: list[Chunk]


# Question shared properties
QuestionBase = Annotated[
        str, 
        StringConstraints(min_length=1, max_length=800, strip_whitespace=True)
    ]


QuestionEmbedding = Annotated[
        list[float],
        Field(sa_type=Vector(1536))
    ]


class Sources(MailBase):
    mail_id: uuid.UUID = Field(foreign_key="mail.id", nullable=False, ondelete="CASCADE")
    chunk_text: str = Field(
        min_length=1, 
        max_length=800, 
    )


class QuestionCreate(SQLModel):
    question: QuestionBase
    answer: str
    sources: list[dict] = Field(default_factory=list, sa_type=JSON)


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
