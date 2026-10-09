# Press O'Clock

**Press O'Clock** is a RAG-based conversational assistant for journalists that centralizes press releases received via email, enabling natural language queries. Built as a full-stack application, it combines a **FastAPI** backend with a **React + TypeScript** frontend.

This project is based on the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template).

---

## Index

- [Demo](#demo)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Environment Configuration](#environment-configuration)
- [Execution](#execution)

---

## Demo

This demo shows the main **Press O'clock** application behavior.

### Preview

![Navigation](readme-images/press-oclock.gif)

### Key Screens

| Login |
|------|
|![Login](readme-images/1.png)|

| Main Dashboard  | Webhook | Inbox |
|------|-------------------|-----------|
| ![Main Dashboard](readme-images/2.png) | ![Webhook](readme-images/3.png) | ![Inbox](readme-images/4.png) |

| Query | Answer + Sources | Quoted Mail |
|------|-------------------|-----------|
| ![Query](readme-images/5.png) | ![Answer + Sources](readme-images/6.png) | ![Quoted Mail](readme-images/7.png) |

---

## Features

### Core Features

- **RAG-based conversational search** - Leverages OpenAI embeddings and pgvector for intelligent similarity search over press releases
- **Optimized context retrieval** - Expands retrieved context with contiguous chunks for better LLM responses
- **Source traceability** - Every response links back to original sources, including text excerpts and email metadata
- **Automated email ingestion** - Make.com webhook integration decouples email capture from internal processing
- **Natural language queries** - Ask questions about your press releases in plain English

### Technology Stack Features

- **Full-stack TypeScript support** with shared types across backend and frontend
- **FastAPI backend** with SQLModel ORM to Supabase for type-safe database operations
- **React + Vite** frontend with modern development experience and hot module replacement
- **JWT authentication** with secure password hashing (Bcrypt)
- **Email-based password recovery** with Mailcatcher for local development
- **Automated API client generation** using OpenAPI/TypeScript codegen
- **Docker Compose** setup for reproducible development and production deployments
- **Traefik reverse proxy** for load balancing and HTTPS termination
- **Comprehensive testing** with Pytest (backend) and Playwright (E2E)
- **Database migrations** using Alembic
- **CI/CD automation** with GitHub Actions
- **Dark mode support** with Tailwind CSS
- **Pre-configured development tools** with linting, formatting, and type checking

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Backend Framework** | FastAPI | ≥0.128.0 |
| **Runtime** | Python | ≥3.12 |
| **Async Server** | Uvicorn | ≥0.40.0 |
| **ORM** | SQLModel | Latest |
| **Data Validation** | Pydantic | ≥2.12.5 |
| **Database** | PostgreSQL | Latest |
| **Frontend Framework** | React | Latest |
| **Build Tool** | Vite | Latest |
| **Language** | TypeScript | Latest |
| **Styling** | Tailwind CSS | Latest |
| **Components** | shadcn/ui | Latest |
| **E2E Testing** | Playwright | Latest |
| **Backend Testing** | Pytest | Latest |
| **Database Migrations** | Alembic | Latest |
| **Authentication** | JWT + Bcrypt | Latest |
| **Reverse Proxy** | Traefik | Latest |
| **Containerization** | Docker, Docker Compose | Latest |

---

## Project Structure

```
press-oclock/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI application entry point
│   │   ├── crud.py                 # Create, Read, Update, Delete operations
│   │   ├── models.py               # SQLModel models (User, Source, Mail, Attachment, Chunk, Question)
│   │   ├── initial_data.py         # Database seeding logic
│   │   ├── backend_pre_start.py    # Waits for the database before migrations
│   │   ├── tests_pre_start.py      # Waits for the database before running tests
│   │   ├── utils.py                # Utility functions (emails, tokens)
│   │   │
│   │   ├── api/
│   │   │   ├── main.py             # Main API router
│   │   │   ├── deps.py             # Dependency injection (auth, DB session, API key)
│   │   │   └── routes/             # Endpoint routes
│   │   │       ├── login.py
│   │   │       ├── mails.py
│   │   │       ├── private.py
│   │   │       ├── questions.py
│   │   │       ├── users.py
│   │   │       └── utils.py
│   │   │
│   │   ├── core/
│   │   │   ├── config.py           # Settings & environment variables
│   │   │   ├── db.py               # Database connection & session management
│   │   │   ├── logging.py          # Structured logging configuration
│   │   │   ├── security.py         # JWT authentication & password hashing
│   │   │   └── openai_client.py    # OpenAI client integration
│   │   │
│   │   ├── services/
│   │   │   ├── mail_service.py     # Mail ingestion & embedding pipeline
│   │   │   └── rag_service.py      # RAG (Retrieval-Augmented Generation)
│   │   │
│   │   ├── integrations/
│   │   │   └── email_provider.py   # Email provider abstraction
│   │   │
│   │   ├── rag/
│   │   │   ├── chunking.py         # Text chunking for embeddings
│   │   │   ├── embedding.py        # Embedding generation
│   │   │   ├── generation.py       # Answer generation logic
│   │   │   ├── retrieval.py        # Similarity search for chunks
│   │   │   ├── augmentation.py     # Contiguous chunk expansion
│   │   │   ├── citations.py        # Citation building from sources
│   │   │   └── metadata.py         # Source metadata aggregation
│   │   │
│   │   ├── email-templates/
│   │   │   ├── src/                # Email template source files
│   │   │   └── build/              # Compiled email templates
│   │   │
│   │   └── alembic/                # Database migration scripts
│   │       ├── env.py
│   │       ├── versions/
│   │       └── script.py.mako
│   │
│   ├── tests/
│   │   ├── api/routes/             # Endpoint tests
│   │   ├── crud/                   # CRUD tests
│   │   ├── rag/                    # RAG pipeline tests
│   │   ├── utils/                  # Test helpers
│   │   ├── scripts/                # Test startup scripts
│   │   └── conftest.py             # Pytest configuration & fixtures
│   │
│   ├── scripts/
│   │   ├── format.sh               # Code formatting script
│   │   ├── lint.sh                 # Linting script
│   │   ├── test.sh                 # Run tests
│   │   ├── prestart.sh             # Pre-startup setup
│   │   └── tests-start.sh          # Start tests in docker
│   │
│   ├── Dockerfile                  # Container image for backend
│   ├── pyproject.toml              # Python project configuration
│   ├── alembic.ini                 # Alembic configuration
│   └── README.md
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx                # React entry point
│   │   ├── index.css               # Global styles
│   │   ├── utils.ts                # Utility functions
│   │   ├── routeTree.gen.ts        # Generated route definitions
│   │   ├── vite-env.d.ts           # Vite environment types
│   │   │
│   │   ├── client/                 # Auto-generated API client (OpenAPI)
│   │   │   ├── core/
│   │   │   ├── index.ts
│   │   │   ├── sdk.gen.ts
│   │   │   ├── types.gen.ts
│   │   │   └── schemas.gen.ts
│   │   │
│   │   ├── components/             # Reusable React components
│   │   │   ├── Admin/
│   │   │   ├── Common/
│   │   │   ├── Items/
│   │   │   ├── Pending/
│   │   │   ├── Sidebar/
│   │   │   ├── UserSettings/
│   │   │   └── ui/
│   │   │
│   │   ├── routes/                 # Route-based components
│   │   ├── hooks/                  # Custom React hooks
│   │   └── lib/                    # Shared utilities & helpers
│   │
│   ├── public/                     # Static assets
│   │
│   ├── tests/
│   │   ├── admin.spec.ts           # Admin feature tests
│   │   ├── auth.setup.ts           # Authentication setup
│   │   ├── login.spec.ts           # Login tests
│   │   ├── sign-up.spec.ts         # Sign-up tests
│   │   ├── items.spec.ts           # Items feature tests
│   │   ├── user-settings.spec.ts   # User settings tests
│   │   ├── reset-password.spec.ts  # Password reset tests
│   │   ├── config.ts               # Test configuration
│   │   └── utils/                  # Test utilities
│   │
│   ├── Dockerfile                  # Container image for frontend
│   ├── Dockerfile.playwright       # Playwright-specific container
│   ├── vite.config.ts              # Vite configuration
│   ├── tsconfig.json               # TypeScript configuration
│   ├── playwright.config.ts        # Playwright configuration
│   ├── openapi-ts.config.ts        # OpenAPI code generation config
│   ├── biome.json                  # Code formatter configuration
│   ├── nginx.conf                  # Nginx configuration
│   ├── package.json
│   └── README.md
│
├── scripts/
│   ├── test-local.sh               # Local testing script
│   ├── test.sh                     # Docker testing script
│   ├── generate-client.sh          # Generate TypeScript client
│   └── add_latest_release_date.py  # Release notes helper
│
├── .github/workflows/              # CI/CD (tests, lint, deploy)
│
├── compose.yml                     # Base Docker Compose configuration
├── compose.override.yml            # Local development overrides
├── compose.traefik.yml             # Traefik reverse proxy configuration
│
├── .env-example                    # Environment variables template
├── pyproject.toml                  # Root project configuration
├── package.json                    # Root Node.js configuration
├── .pre-commit-config.yaml         # Pre-commit hooks
├── copier.yml                      # Project template configuration
│
├── deployment.md                   # Deployment guide
├── development.md                  # Development guide
├── CONTRIBUTING.md                 # Contribution guidelines
├── LICENSE
└── README.md

```

---

## Installation

### Prerequisites

- **Python 3.12+**
- **Node.js 18+** (for frontend)
- **pip** or **uv** package manager
- **Git** (for cloning the repository)
- **ngrok** (optional - required for Make.com webhook integrations during development)

### Option 1: Using pip + npm

```bash
# Clone the repository
git clone https://github.com/yourusername/press-oclock.git
cd press-oclock

# Setup Backend
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install backend dependencies
pip install -e .
pip install -e ".[dev]"

# Return to root
cd ..

# Setup Frontend
cd frontend
npm install
cd ..
```

### Option 2: Using uv + pnpm

```bash
# Install uv (one-time)
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and navigate
git clone https://github.com/yourusername/press-oclock.git
cd press-oclock

# Backend setup
cd backend
uv sync
cd ..

# Frontend setup
cd frontend
npm install  # or pnpm install
cd ..
```

### Option 3: Using Docker Compose (Recommended for Development)

```bash
# Clone the repository
git clone https://github.com/yourusername/press-oclock.git
cd press-oclock

# Build and run all services
docker-compose up --build

# Services will be accessible at:
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# API Documentation: http://localhost:8000/docs
# Traefik Dashboard: http://localhost:8080
```

---

## Environment Configuration

### 1. Backend Setup

All backend settings are read from a single `.env` file at the **repository root** (the backend loads `../.env`, one level above `backend/`). Start from the provided template:

```bash
cp .env-example .env
```

```env
# Domain & environment
DOMAIN=localhost
FRONTEND_HOST=http://localhost:5173
ENVIRONMENT=local                 # local | staging | production
PROJECT_NAME="Press O'Clock"
STACK_NAME=press-oclock-project
BACKEND_CORS_ORIGINS=http://localhost,http://localhost:5173

# Security
SECRET_KEY=your_secret_key
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=your_first_superuser_password

# Email / SMTP (used for password recovery)
SMTP_HOST=
SMTP_PORT=587
SMTP_TLS=True
SMTP_SSL=False
SMTP_USER=
SMTP_PASSWORD=
EMAILS_FROM_EMAIL=info@example.com

# Database (Postgres / Supabase)
POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password
# Optional: full DSN (postgresql+psycopg://user:pass@host:port/db) to use Supabase instead of local Postgres
SUPABASE_DATABASE_URL=
SENTRY_DSN=

# Make.com webhook integration
MAKE_API_KEY=your_make_api_key
MAIL_WEBHOOK_USER_ID=00000000-0000-0000-0000-000000000000

# Supabase Storage (required for email attachment ingestion)
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_backend_only_service_role_key
SUPABASE_STORAGE_BUCKET=mail-attachments
MAIL_ATTACHMENT_MAX_BYTES=5000000
MAIL_ATTACHMENT_STORAGE_RETRIES=3
MAIL_STAGE_TTL_HOURS=24
MAIL_STAGE_RETENTION_DAYS=30

# OpenAI models
OPENAI_API_KEY=your_openai_api_key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
GENERATION_MODEL=gpt-4o-mini

# Docker images (used by Docker Compose)
DOCKER_IMAGE_BACKEND=backend
DOCKER_IMAGE_FRONTEND=frontend
```

The following variables are **required** — the app will not start without them: `SECRET_KEY`, `PROJECT_NAME`, `POSTGRES_SERVER`, `POSTGRES_USER`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, `MAKE_API_KEY`, `MAIL_WEBHOOK_USER_ID`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` and `GENERATION_MODEL`. `MAIL_WEBHOOK_USER_ID` must be a valid UUID and should reference an existing user, since incoming mails are attributed to it. The API prefix (`/api`) and token/email-reset expirations have safe defaults.

Email attachment ingestion additionally requires a private Supabase Storage bucket matching `SUPABASE_STORAGE_BUCKET`. Keep `SUPABASE_SERVICE_ROLE_KEY` on the backend only. Expired staged uploads and pending Storage deletions can be cleaned by scheduling `python -m app.cleanup_mail_ingestions` from the backend directory.

The Make scenario starts an ingestion with `POST /api/mails/stages`, uploads each file as `multipart/form-data` to `POST /api/mails/stages/{ingestion_id}/attachments` (`file`, `external_id`, and optional `mime_type` fields), then calls `POST /api/mails/stages/{ingestion_id}/finalize` after its attachment iterator completes. The API enforces a 5 MB (5,000,000-byte) total attachment limit per staged mail.

If the start response reports `status=completed`, the Gmail message was already ingested and Make should skip the attachment iterator and finalization.

### 2. Frontend Setup

The frontend reads `VITE_API_URL` as the API **origin** — the generated client already appends the `/api` prefix:

```env
# frontend/.env
VITE_API_URL=http://localhost:8000
```

### 3. Docker Compose

Local development is wired through `compose.override.yml`, which publishes the service ports (`frontend:5173`, `backend:8000`, `adminer:8080`, `db:5432`, `mailcatcher:1080`) and routes outgoing email through Mailcatcher (`SMTP_HOST=mailcatcher`, `SMTP_PORT=1025`). Prefer adjusting values in the root `.env` over editing the compose files; `.env-example` is the reference for every supported variable.

---

## Execution

### Development Backend

```bash
# Navigate to backend
cd backend

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Start development server with auto-reload
python -m uvicorn app.main:app --reload --port 8000

# Or using uv:
uv run uvicorn app.main:app --reload
```

Backend API documentation will be at: **http://localhost:8000/docs**

### Development with Make/Webhooks (ngrok)

If your application uses **Make.com webhooks** or needs to receive external HTTP callbacks during development, you'll need to expose your local backend to the internet using `ngrok` in another terminal.

#### Install ngrok

**Windows (using Chocolatey):**
```bash
choco install ngrok
# Run 
ngrok http 8000
```

### Development Frontend

```bash
# Navigate to frontend
cd frontend

# Start development server
npm run dev
# or
pnpm dev
# or
bun run dev
```

Frontend will be at: **http://localhost:5173**

### Development with Docker Compose

```bash
# Start all services with live reload
docker-compose up

# In another terminal, run migrations if needed
docker-compose exec backend alembic upgrade head

# Access services:
# Frontend: http://localhost:5173
# Backend: http://localhost:8000
# Docs: http://localhost:8000/docs

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Production Deployment

```bash
# Using the production compose configuration
docker-compose -f compose.yml -f compose.traefik.yml up -d

# With Traefik for SSL/HTTPS
# Configure your domain in compose.traefik.yml
```

---

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

**Press O'Clock**
