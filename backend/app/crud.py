from typing import Any
from uuid import UUID

from sqlmodel import Session, col, delete, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Attachment,
    AttachmentStage,
    Chunk,
    ChunkCreate,
    Mail,
    MailCreate,
    MailStage,
    Message,
    Question,
    QuestionCreate,
    Source,
    StorageCleanup,
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
    # Si se hiciese .flush() aquí registraría la fuente antes de asociarla a mail, .add() simplemente la añade a la sesión
    session.add(db_source)
    return db_source


def create_mail(
    *,
    session: Session,
    mail_in: MailCreate,
    user_id: UUID,
    external_id: str | None = None,
    commit: bool = True,
) -> Mail:
    db_source = create_source(session=session, origin="mail", user_id=user_id)
    db_mail = Mail.model_validate(
        mail_in,
        update={
            "user_id": user_id,
            "source_id": db_source.id,
            "external_id": external_id,
        },
    )
    db_mail.source = db_source
    session.add(db_mail)
    # .commit() está indicado para que crud.py recoja la lógica de las transacciones, aunque se ejecute de facto en el archivo que llama a esta función
    if commit:
        session.commit()
        session.refresh(db_mail)
    else:
        # .flush() registra en la base de datos pero deja la transacción abierta a diferencia de .commit()
        session.flush()
    return db_mail


def create_chunks(
    *,
    session: Session,
    chunks_in: list[ChunkCreate],
    source_id: UUID,
    commit: bool = True,
) -> Message:
    for chunk in chunks_in:
        db_chunk = Chunk.model_validate(chunk, update={"source_id": source_id})
        session.add(db_chunk)
    if commit:
        session.commit()
    else:
        session.flush()
    return Message(message="Chunks created successfully")


def create_storage_cleanup(*, session: Session, storage_path: str) -> None:
    existing_storage_attachment = session.exec(
        select(StorageCleanup).where(StorageCleanup.storage_path == storage_path)
    ).first()
    if existing_storage_attachment is None:
        session.add(StorageCleanup(storage_path=storage_path))


def get_pending_storage_cleanup(
    *, session: Session, limit: int
) -> list[StorageCleanup]:
    statement = (
        select(StorageCleanup)
        .order_by(col(StorageCleanup.created_at))
        .limit(limit)
    )
    return list(session.exec(statement).all())


def delete_mail(*, session: Session, mail_in: Mail) -> list[str]:
    """CAMBIAR Borra un correo, sus fuentes/chunks y registra sus ficheros para limpieza."""
    attachment_source_ids = list(
        session.exec(
            select(Attachment.source_id).where(Attachment.mail_id == mail_in.id)
        ).all()
    )
    source_ids = [mail_in.source_id, *attachment_source_ids]
    storage_paths = list(
        session.exec(
            select(Attachment.storage_path).where(Attachment.mail_id == mail_in.id)
        ).all()
    )

    if mail_in.external_id:
        matching_stages = list(
            session.exec(
                select(MailStage).where(
                    MailStage.user_id == mail_in.user_id,
                    MailStage.external_id == mail_in.external_id,
                )
            ).all()
        )
        for stage in matching_stages:
            stage_paths = session.exec(
                select(AttachmentStage.storage_path).where(
                    col(AttachmentStage.mail_stage_id) == stage.id,
                    col(AttachmentStage.storage_path).is_not(None),
                )
            ).all()
            storage_paths.extend(path for path in stage_paths if path)
            session.delete(stage)

    for storage_path in set(storage_paths):
        create_storage_cleanup(session=session, storage_path=storage_path)

    if source_ids:
        session.exec(delete(Chunk).where(col(Chunk.source_id).in_(source_ids)))
    session.exec(
        delete(Attachment).where(col(Attachment.mail_id) == mail_in.id)
    )
    session.delete(mail_in)
    session.flush()

    if source_ids:
        session.exec(delete(Source).where(col(Source.id).in_(source_ids)))

    return storage_paths


def delete_user_mails(*, session: Session, user_id: UUID) -> list[str]:
    storage_paths: list[str] = []
    mails = session.exec(select(Mail).where(Mail.user_id == user_id)).all()
    for mail in mails:
        storage_paths.extend(delete_mail(session=session, mail_in=mail))

    stages = session.exec(select(MailStage).where(MailStage.user_id == user_id)).all()
    for stage in stages:
        stage_paths = session.exec(
            select(AttachmentStage.storage_path).where(
                col(AttachmentStage.mail_stage_id) == stage.id,
                col(AttachmentStage.storage_path).is_not(None),
            )
        ).all()
        storage_paths.extend(path for path in stage_paths if path)
        session.delete(stage)

    for storage_path in set(storage_paths):
        create_storage_cleanup(session=session, storage_path=storage_path)

    session.flush()
    return storage_paths


def delete_storage_cleanup(
    *, session: Session, cleanup: StorageCleanup
) -> None:
    session.delete(cleanup)
    session.flush()


def get_expired_mail_stages(
    *, session: Session, receiving_before: Any, completed_before: Any
) -> list[MailStage]:
    statement = select(MailStage).where(
        ((MailStage.status == "receiving") & (MailStage.created_at < receiving_before))
        | ((MailStage.status == "completed") & (MailStage.created_at < completed_before))
    )
    return list(session.exec(statement).all())


def delete_mail_stage(*, session: Session, stage: MailStage) -> list[str]:
    storage_paths = list(
        session.exec(
            select(AttachmentStage.storage_path).where(
                col(AttachmentStage.mail_stage_id) == stage.id,
                col(AttachmentStage.storage_path).is_not(None),
            )
        ).all()
    )
    paths = [path for path in storage_paths if path]
    for storage_path in set(paths):
        create_storage_cleanup(session=session, storage_path=storage_path)
    session.delete(stage)
    session.flush()
    return paths


def create_question(*, session: Session, question_in: QuestionCreate, user_id: UUID) -> Question:
    db_question = Question.model_validate(question_in, update={"user_id": user_id})
    session.add(db_question)
    session.commit()
    session.refresh(db_question)
    return db_question


def delete_question(*, session: Session, question: Question) -> None:
    session.delete(question)
    session.flush()
