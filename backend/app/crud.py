from typing import Any
from uuid import UUID

from sqlmodel import Session, col, delete, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Chunk,
    ChunkCreate,
    Mail,
    MailCreate,
    Message,
    Question,
    QuestionCreate,
    Source,
    User,
    UserCreate,
    UserUpdate,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    password = user_data.pop("password", None)
    if password is not None:
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_source(*, session: Session, origin: str, user_id: UUID) -> Source:
    """Create a source owned by a user without committing the transaction."""
    db_source = Source(origin=origin, user_id=user_id)
    session.add(db_source)
    return db_source


def create_mail(*, session: Session, mail_in: MailCreate, user_id: UUID) -> Mail:
    db_source = create_source(session=session, origin="mail", user_id=user_id)
    db_mail = Mail.model_validate(
        mail_in,
        update={"user_id": user_id, "source_id": db_source.id},
    )
    db_mail.source = db_source
    session.add(db_mail)
    session.commit()
    session.refresh(db_mail)
    return db_mail


def create_chunks(
    *, session: Session, chunks_in: list[ChunkCreate], source_id: UUID
) -> Message:
    for chunk in chunks_in:
        db_chunk = Chunk.model_validate(chunk, update={"source_id": source_id})
        session.add(db_chunk)
    session.commit()
    return Message(message="Chunks created successfully")


def delete_mail(*, session: Session, mail_in: Mail) -> None:
    """Borra un mail, sus chunks, y la source del que depende"""
    source_id = mail_in.source_id
    session.exec(delete(Chunk).where(col(Chunk.source_id) == source_id))
    session.delete(mail_in)
    session.flush()

    source = session.get(Source, source_id)
    if source is not None:
        session.delete(source)


def delete_user_mails(*, session: Session, user_id: UUID) -> None:
    mails = session.exec(select(Mail).where(Mail.user_id == user_id)).all()
    for mail in mails:
        delete_mail(session=session, mail_in=mail)


def create_question(*, session: Session, question_in: QuestionCreate, user_id: UUID) -> Question:
    db_question = Question.model_validate(question_in, update={"user_id": user_id})
    session.add(db_question)
    session.commit()
    session.refresh(db_question)
    return db_question


def delete_question(*, session: Session, question: Question) -> None:
    session.delete(question)
    session.flush()
