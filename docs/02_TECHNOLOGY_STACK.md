# 02. Technology Stack Specification
### توثيق التقنيات والمكتبات المستخدمة فعلياً في المشروع

This document specifies the exact software technologies, runtime environments, libraries, frameworks, and protocols verified to be in active use in the **RECRM** codebase.

---

## 1. Summary Matrix of Technologies

| Category | Technology | Verified Version | Configuration Location | Primary Responsibility |
|---|---|---|---|---|
| **Programming Language** | **Python** | 3.14.4 / 3.12+ | System runtime / `.venv` | Backend language for all business logic, routing, and data processing. |
| **Backend Framework** | **FastAPI** | 0.161.1 | [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py) | High-performance asynchronous REST API framework. |
| **ASGI Web Server** | **Uvicorn** | 0.54.0 | [`src/backend/run.py`](file:///home/nemro/RECRM/src/backend/run.py) | Lightning-fast asynchronous server hosting the FastAPI application. |
| **Data Validation & Typing** | **Pydantic** | 2.14.1 | [`src/backend/app/schemas/`](file:///home/nemro/RECRM/src/backend/app/schemas) | Data serialization, request payload parsing, and response contracts. |
| **Configuration Engine** | **pydantic-settings**| 2.16.1 | [`src/backend/app/config.py`](file:///home/nemro/RECRM/src/backend/app/config.py) | Typesafe environment variables parsed from `.env`. |
| **Database Engine** | **PostgreSQL** | 18.0 / 16.0 | System service (port 5432) | ACID-compliant relational database storing all 53 tables. |
| **Database Driver** | **asyncpg** | 0.32.0 | [`src/backend/app/database.py`](file:///home/nemro/RECRM/src/backend/app/database.py) | Low-level asynchronous binary driver for PostgreSQL connection pooling. |
| **Frontend Foundation** | **HTML5 / CSS3 / ES6+**| Native Browser | [`src/ui/`](file:///home/nemro/RECRM/src/ui) | Semantic mark-up, CSS custom properties, and client-side logic (zero Node.js build tools). |
| **Arabic Typography** | **Cairo, Tajawal, Almarai**| Web fonts | Local fonts / Google Fonts | Native Right-to-Left (RTL) Arabic typography and layout system. |
| **Testing Framework** | **pytest** | 9.1.1 | [`tests/`](file:///home/nemro/RECRM/tests) | Automated integration and regression test runner. |
| **Async Test Plugin** | **pytest-asyncio** | 1.4.0 | [`tests/`](file:///home/nemro/RECRM/tests) | Enables `unittest.IsolatedAsyncioTestCase` and async fixtures. |
| **HTTP Client (Testing)** | **HTTPX** | 0.28.1 | [`tests/`](file:///home/nemro/RECRM/tests) | Underpins FastAPI's `TestClient` for synchronous and async API testing. |

---

## 2. Detailed Technology Breakdown

### 2.1. Backend Technologies

#### A. Python (Version 3.14.4 / 3.12+)
- **Role**: Core backend programming language.
- **Where Configured**: Linux system runtime, virtual environment at `.venv/`.
- **Evidence**: Verified via `.venv/bin/python --version` yielding `Python 3.14.4`. Python 3.12+ type hinting features (such as `typing.Optional`, `typing.List`, and async/await syntax) are utilized across all backend source files.
- **Why Used**: Clean syntax, exceptional support for asynchronous I/O (`asyncio`), and rich native mathematical capabilities for real estate calculations.

#### B. FastAPI (Version 0.161.1)
- **Role**: REST API framework and router.
- **Where Configured**: Instantiated in [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L53); routers declared in [`src/backend/app/routers/`](file:///home/nemro/RECRM/src/backend/app/routers).
- **Evidence**: `app = FastAPI(...)` in `main.py`; 16 modular sub-routers included with `app.include_router(...)`.
- **Why Used**: High performance, native OpenAPI (Swagger) documentation generation at `/docs`, asynchronous request handlers, and deep integration with Pydantic for validation.

#### C. Uvicorn (Version 0.54.0)
- **Role**: Asynchronous Server Gateway Interface (ASGI) web server.
- **Where Configured**: [`src/backend/run.py`](file:///home/nemro/RECRM/src/backend/run.py#L8).
- **Evidence**: `uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)` is called when executing `run.py`.
- **Why Used**: Standards-compliant ASGI server that efficiently handles thousands of concurrent WebSocket and HTTP connections with minimal memory footprint.

#### D. Pydantic (Version 2.14.1) & Pydantic-Settings (Version 2.16.1)
- **Role**: Data parsing, schema validation, and environment configuration.
- **Where Configured**: Configuration in [`src/backend/app/config.py`](file:///home/nemro/RECRM/src/backend/app/config.py); request/response schemas in [`src/backend/app/schemas/`](file:///home/nemro/RECRM/src/backend/app/schemas).
- **Evidence**: All router endpoint functions take inputs typed with Pydantic models (e.g. `payload: LeadCreateIn`, `payload: OpportunityUpdate`), returning structured `ResponseEnvelope[T]`.
- **Why Used**: Enforces strict type safety and data integrity before requests ever touch the business logic or database.

---

## 3. Database & Persistence Layer

#### A. PostgreSQL (Version 18 / 16)
- **Role**: Relational Database Management System (RDBMS).
- **Where Configured**: Database connection parameters in `.env` (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`).
- **Evidence**: 53 verified public tables and 45 sequences in the `re_db` database. Foreign keys, check constraints, unique constraints, and sequential ID generators are implemented at the database level.
- **Why Used**: Extreme reliability, enterprise ACID compliance, native JSONB support (used in `workflow_sop_guidance`), row-level concurrency locks (`FOR UPDATE`), and robust sequence generators.

#### B. asyncpg (Version 0.32.0)
- **Role**: Direct PostgreSQL connection pool and binary query driver.
- **Where Configured**: Initialized in [`src/backend/app/database.py`](file:///home/nemro/RECRM/src/backend/app/database.py#L13).
- **Evidence**: `pool = await asyncpg.create_pool(...)` creates a pool with `min_size=2` and `max_size=20`. Routers inject connections via `conn: asyncpg.Connection = Depends(get_db)`.
- **Why Used**: asyncpg is recognized as the fastest PostgreSQL driver for Python—substantially faster than Psycopg2 or SQLAlchemy ORM—because it speaks the PostgreSQL binary protocol directly and avoids heavy object-relational mapping overhead.
- **Important Note**: While `SQLAlchemy` is present in `requirements.txt`, **the active codebase does not use SQLAlchemy ORM or Alembic migrations**. All queries are pure, parameterized asyncpg SQL statements.

---

## 4. Frontend Technologies

#### A. Pure Vanilla JavaScript (ES6+), HTML5, and CSS3
- **Role**: Complete user interface and client-side application logic.
- **Where Configured**: [`src/ui/`](file:///home/nemro/RECRM/src/ui). Mounted statically by FastAPI in `main.py` at `/ui`.
- **Evidence**: 12 standalone HTML files (`index.html`, `leads.html`, `sales.html`, etc.) accompanied by shared utility libraries [`common.js`](file:///home/nemro/RECRM/src/ui/common.js) and [`user_session.js`](file:///home/nemro/RECRM/src/ui/user_session.js).
- **Why Used**: 
  - Zero build step: No Node.js, Webpack, Vite, or npm required.
  - Zero deployment friction: Changes in HTML/JS take effect immediately upon browser refresh.
  - Longevity & Stability: Plain web standards do not suffer from framework churn or broken npm dependency trees.

#### B. CSS Custom Properties & Responsive Design Tokens
- **Role**: Unified design system across all 12 operational portals.
- **Where Configured**: Declared in `<style>` blocks in each portal and dynamically augmented by `common.js`.
- **Evidence**: Consistent color palette tokens:
  - `--primary`: `#1e3a8a` (Deep Saudi Institutional Blue)
  - `--secondary`: `#0284c7` (Sky Blue)
  - `--success`: `#16a34a` (Saudi Green)
  - `--warning`: `#d97706` (Amber)
  - `--danger`: `#dc2626` (Red)
  - `--background`: `#f8fafc` / `--surface`: `#ffffff`
- **Typography**: Local and web-loaded Arabic font stack: `'Cairo', 'Tajawal', 'Almarai', -apple-system, sans-serif`.

---

## 5. Testing & Verification Tooling

#### A. pytest (Version 9.1.1) & pytest-asyncio (Version 1.4.0)
- **Role**: Test discovery and execution framework.
- **Where Configured**: Test files in [`tests/`](file:///home/nemro/RECRM/tests).
- **Evidence**: 31 comprehensive test suites covering 198 automated test scenarios.
- **Command**: `PYTHONPATH=src/backend .venv/bin/pytest tests/ -v`.
- **Why Used**: Industry standard Python test framework with fixtures, parameterized test inputs, and seamless asynchronous testing support.

#### B. FastAPI TestClient (HTTPX 0.28.1)
- **Role**: In-memory HTTP client for testing API routes without binding to external network ports.
- **Evidence**: `from fastapi.testclient import TestClient` used in `test_cancellation_workflows.py`, `test_customer_business_rules.py`, and `test_saudi_fees_and_invoices.py`.

---

## 6. Distinguishing Confirmed Facts from Inference

| Fact / Component | Status | Source of Evidence |
|---|---|---|
| **Python 3.14 + FastAPI + asyncpg** | **CONFIRMED** | Inspectable in `src/backend/app/`, `requirements.txt`, and runtime. |
| **PostgreSQL 53 tables & 45 sequences** | **CONFIRMED** | Direct query verification against PostgreSQL `re_db`. |
| **No Node.js or npm dependencies** | **CONFIRMED** | Absence of `package.json`, `node_modules`, or build scripts. |
| **ZATCA Phase 2 Cloud Webhooks** | **INFERRED ABSENT** | Code generates compliant XML/HTML invoices and QR codes, but no live cryptographic TLS handshake to ZATCA servers exists in code. |
| **SQLAlchemy ORM Models** | **INFERRED UNUSED** | SQLAlchemy is listed in `requirements.txt`, but zero ORM model classes or declarative bases exist in `src/backend/app/`. asyncpg is used directly everywhere. |
| **External SMS Gateway** | **INFERRED ABSENT** | Phone calls and WhatsApp messages are logged to the `communications` table, but no external HTTP SMS API keys (e.g. Twilio) exist in `config.py`. |

