# Press O'Clock

**Press O'Clock** is a RAG-based conversational assistant for journalists that centralizes press releases received via email, enabling natural language queries. Built as a full-stack application, it combines a **FastAPI** backend with a **React + TypeScript** frontend.

This project is based on the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template).

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
│   │   ├── models.py               # SQLModel database models
│   │   ├── initial_data.py         # Database seeding logic
│   │   ├── utils.py                # Utility functions
│   │   │
│   │   ├── api/
│   │   │   ├── main.py             # Main API router
│   │   │   ├── deps.py             # Dependency injection
│   │   │   └── routes/             # Endpoint routes (items, users, etc.)
│   │   │
│   │   ├── core/
│   │   │   ├── db.py               # Database connection & session management
│   │   │   ├── logging.py          # Structured logging configuration
│   │   │   ├── security.py         # JWT authentication & password hashing
│   │   │   └── openai_client.py    # Optional: External API integrations
│   │   │
│   │   ├── services/
│   │   │   ├── mail_service.py     # Email sending service
│   │   │   ├── rag_service.py      # RAG (Retrieval-Augmented Generation)
│   │   │   └── sync_service.py     # Data synchronization
│   │   │
│   │   ├── integrations/
│   │   │   ├── email_provider.py   # Email provider abstraction
│   │   │   └── gmail_provider.py   # Gmail-specific implementation
│   │   │
│   │   ├── rag/
│   │   │   ├── chunking.py         # Text chunking for embeddings
│   │   │   ├── embeddings.py       # Embedding generation
│   │   │   ├── generation.py       # Generation logic
│   │   │   ├── retrieval_augmentation.py
│   │   │   └── sources.py          # Data source management
│   │   │
│   │   ├── email-templates/
│   │   │   ├── src/                # Email template source files
│   │   │   └── build/              # Compiled email templates
│   │   │
│   │   ├── alembic/                # Database migration scripts
│   │   │   ├── env.py
│   │   │   ├── versions/
│   │   │   └── script.py.mako
│   │   │
│   │   └── tests/                  # Backend tests
│   │       ├── api/
│   │       ├── crud/
│   │       ├── utils/
│   │       ├── conftest.py         # Pytest configuration & fixtures
│   │       └── scripts/
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
│   │   ├── client/
│   │   │   └── index.ts            # Auto-generated API client
│   │   │
│   │   ├── components/             # Reusable React components
│   │   │
│   │   ├── routes/                 # Route-based components
│   │   │
│   │   ├── hooks/                  # Custom React hooks
│   │   │
│   │   └── lib/                    # Shared utilities & helpers
│   │
│   ├── public/                     # Static assets
│   │   └── assets/
│   │       └── images/
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
├── alembic/                        # Root-level migrations (if applicable)
│   ├── env.py
│   ├── versions/
│   └── script.py.mako
│
├── scripts/
│   ├── test-local.sh               # Local testing script
│   ├── test.sh                     # Docker testing script
│   └── generate-client.sh          # Generate TypeScript client
│
├── docker-compose.yml              # Main compose configuration
├── compose.yml                     # Alternative compose
├── compose.override.yml            # Local development overrides
├── compose.traefik.yml             # Traefik configuration
│
├── pyproject.toml                  # Root project configuration
├── package.json                    # Root Node.js configuration
├── copier.yml                      # Project template configuration
├── alembic.ini                     # Root Alembic configuration
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

Navigate to `backend/` and create a `.env` file based on the template:

```env
# Database Configuration
POSTGRES_SERVER=db
POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://postgres:changeme@localhost/app

# FastAPI Configuration
APP_NAME=Press O'Clock
APP_VERSION=0.1.0
DEBUG=true

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# JWT Configuration
JWT_SECRET_KEY=your-super-secret-key-change-this
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=30

# CORS Configuration
CORS_ORIGINS=["http://localhost:5173", "http://localhost:3000"]
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=["*"]
CORS_ALLOW_HEADERS=["*"]

# Logging Configuration
LOG_LEVEL=INFO

# Email Configuration (for password recovery)
SMTP_HOST=localhost
SMTP_PORT=1025  # Mailcatcher port
SMTP_USER=
SMTP_PASSWORD=
EMAILS_FROM_EMAIL=noreply@example.com
EMAILS_FROM_NAME=Press O'Clock

# Backend URL (for frontend)
BACKEND_URL=http://localhost:8000

# Optional: External API Keys
OPENAI_API_KEY=your_openai_api_key_here
```

### 2. Frontend Setup

Navigate to `frontend/` and create a `.env` file:

```env
# Backend API URL
VITE_API_URL=http://localhost:8000/api/v1
```

### 3. Update Docker Compose Variables

Edit `compose.override.yml` for local development:

```yaml
services:
  db:
    environment:
      - POSTGRES_PASSWORD=changeme

  backend:
    environment:
      - DATABASE_URL=postgresql://postgres:changeme@db:5432/app
      - JWT_SECRET_KEY=your-super-secret-key
```

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