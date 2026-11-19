import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]

# Debe ejecutarse antes de importar app: settings y engine se crean durante la importación
os.environ["TEST_ENV_FILE"] = str(BACKEND_DIRECTORY / "tests" / "test.env")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from tests.utils.database_guard import ensure_test_database
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


def clear_database(session: Session) -> None:
    # Los metadatos incluyen todas las tablas de los modelos, así que una tabla nueva se vacía sin tocar esta lista.
    # alembic_version no forma parte de ellos y conserva la versión del esquema.
    table_names = ", ".join(
        f'"{table.name}"' for table in SQLModel.metadata.sorted_tables
    )
    # Session.exec no admite SQL en texto, así que se ejecuta sobre la conexión de la sesión
    session.connection().execute(
        text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
    )
    session.commit()


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    ensure_test_database(engine.url)
    # Un subproceso evita que fileConfig de Alembic desactive los loggers de los tests
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIRECTORY,
        check=True,
    )
    with Session(engine) as session:
        # También al principio, por si una ejecución interrumpida dejó datos en la base
        clear_database(session)
        init_db(session)
        yield session
        clear_database(session)


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
