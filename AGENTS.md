# AGENTS.md — Press O'Clock

## 1. REGLA CRÍTICA: Protección de la Base de Datos (PROHIBIDO ejecutar tests sin permiso explícito)

El proyecto utiliza actualmente la misma base de datos configurada en `.env` tanto para desarrollo como para los tests. En `backend/tests/conftest.py`, la fixture `db()` está definida con `autouse=True`, por lo que **cualquier invocación de `pytest` (incluso de un único test unitario en `tests/unit/` que no use la fixture `db`) se conecta a la base de datos y ejecuta un `DELETE` masivo sobre todas las tablas (`Question`, `Chunk`, `AttachmentStage`, `MailStage`, `StorageCleanup`, `Attachment`, `Mail`, `Source` y `User`) al finalizar la sesión**.

Por lo tanto, **bajo ninguna circunstancia ejecutes los siguientes comandos para verificar cambios**:

- **PROHIBIDO ejecutar `pytest`** (ni completo, ni sobre carpetas o archivos individuales como `pytest tests/unit/...`, ni mediante `uv run pytest` o `.venv/Scripts/pytest`).
- **PROHIBIDO ejecutar scripts de tests**:
  - `scripts/test.sh`
  - `scripts/test-local.sh`
  - `backend/scripts/test.sh`
  - `backend/scripts/tests-start.sh`
- **PROHIBIDO ejecutar tests E2E de Playwright**:
  - `bun run test`
  - `bun run test:ui`
  - `bunx playwright test`
- **PROHIBIDO ejecutar comandos destructivos contra la base de datos o volúmenes**:
  - `docker compose down -v` / `docker-compose down -v`
  - `alembic downgrade`
  - Cualquier script o comando en Python/SQL que ejecute `DELETE`, `TRUNCATE` o `DROP` sobre las tablas de la base de datos.

> **Excepción:** Si el usuario pide explícitamente ejecutar un test o si una tarea requiere obligatoriamente correr `pytest` o Playwright, **detente antes de ejecutarlo y pide confirmación explícita al usuario**, recordándole que la ejecución borrará los usuarios y datos actuales de la base de datos.

---

## 2. Comandos de Verificación Seguros (Permitidos)

Para verificar cambios de código en el día a día, utiliza **únicamente** herramientas de análisis estático, chequeo de tipos y compilación (no abren conexión ni modifican la base de datos):

### Backend (`backend/`)
```bash
# Linter y formato (Ruff)
uv run --project backend ruff check backend/app
uv run --project backend ruff format --check backend/app

# Chequeo estático de tipos (Mypy / ty)
uv run --project backend mypy backend/app
uv run --project backend ty check backend/app
```

### Frontend (`frontend/`)
```bash
# Linter y formato (Biome)
bun run lint

# Chequeo de tipos TypeScript y build de producción (tsc + Vite)
bun run --filter frontend build
```

### Cliente OpenAPI (cuando cambien esquemas o rutas del backend)
```bash
# Genera openapi.json importando app.main en memoria (no toca la BD) y actualiza frontend/src/client/
bash ./scripts/generate-client.sh
```

---

## 3. Convenciones Clave del Proyecto

- **Stack Backend:** Python 3.14 (`>=3.14,<3.15`) gestionado con `uv` (`backend/pyproject.toml` y `backend/uv.lock`), FastAPI, SQLModel, PostgreSQL/Supabase con `pgvector`, Alembic, LangChain / LangGraph (`langchain-openai`, `langchain-typesafe`).
- **Stack Frontend:** React 19, TypeScript, Vite, TanStack Router y TanStack Query, Tailwind CSS + shadcn/ui, gestionado con `bun` (`package.json` en raíz con workspace `frontend/`).
- **Variables de entorno:** Se cargan desde el archivo `.env` en la raíz del repositorio (`../.env` respecto a `backend/`). Nunca modifiques ni expongas secretos de `.env`.
