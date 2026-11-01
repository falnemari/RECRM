# RECRM — Saudi Real Estate Brokerage Agency Platform
### نظام معاذ خضر النمري للخدمات العقارية

[![Python](https://img.shields.io/badge/Python-3.14%20%7C%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.161.1-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%20%7C%2016-336791.svg)](https://www.postgresql.org/)
[![Tests](https://img.shields.io/badge/Tests-198%20Passed%20(100%25)-brightgreen.svg)]()
[![Compliance](https://img.shields.io/badge/Compliance-REGA%20%7C%20Ejar%20%7C%20ZATCA%20%7C%20Taqeem-green.svg)]()

A comprehensive, production-ready Real Estate Customer Relationship Management (CRM), Enterprise Brokerage Pipeline, and Property Management system tailored specifically to the statutory regulations and market practices of the Kingdom of Saudi Arabia.

---

## 📌 Table of Contents
1. [Application Purpose & Overview](#-application-purpose--overview)
2. [Current Implementation Status](#-current-implementation-status)
3. [Technology Stack](#-technology-stack)
4. [Key Verified Features](#-key-verified-features)
5. [Repository Structure](#-repository-structure)
6. [Prerequisites](#-prerequisites)
7. [Installation & Setup](#-installation--setup)
8. [Environment Configuration](#-environment-configuration)
9. [Database Initialization](#-database-initialization)
10. [Running the Application](#-running-the-application)
11. [Running Tests](#-running-tests)
12. [Documentation Directory](#-documentation-directory)

---

## 🏢 Application Purpose & Overview

**RECRM** is built for real estate brokerages, facility managers, and investment advisory firms operating under Saudi Arabia's Real Estate General Authority (**REGA** / الهيئة العامة للعقار). The platform replaces disparate spreadsheets and manual follow-ups with an integrated, rules-governed workflow engine.

Rather than forcing every customer down an identical path, RECRM recognizes the customer's intent:
- **🔑 Renting (إيجار)**: Property matching, scheduling viewings, tenancy agreements via the Saudi Ejar standard, automated rent collection installments, and maintenance work orders.
- **🏠 Buying (شراء)**: Budget qualification, property visits, offer submissions, 48-hour earnest deposit reservations, statutory fee calculation (2.5% brokerage fee + 15% VAT + 5% RETT), and contract execution.
- **📈 Investment (استثمار)**: Technical due diligence inspections, structural/HVAC audits, Net Operating Income (NOI), Capitalization Rate (Cap Rate), Cash-on-Cash Return, CapEx defect price adjustments, and multi-asset portfolio comparisons.

---

## 📊 Current Implementation Status

- **Status**: **Stage 1 & Stage 2 Transition Completed** (Production-Grade Operational System).
- **Backend Quality**: 198 automated unit and integration tests passing (**100% pass rate**).
- **Database**: 53 PostgreSQL tables, 45 sequences, zero orphaned records, full referential integrity.
- **Frontend**: 12 operational portals built in responsive Vanilla HTML5/CSS3/JavaScript with RTL-first layout, Cairo/Tajawal typography, and dual-language (Arabic/English) support.

---

## 💻 Technology Stack

| Layer | Technology | Details |
|---|---|---|
| **Backend Framework** | **FastAPI 0.161.1** | Asynchronous Python REST API running on Starlette 1.9.0 |
| **ASGI Web Server** | **Uvicorn 0.54.0** | High-performance ASGI server with auto-reload in dev |
| **Data Validation** | **Pydantic 2.14.1** | Strict request/response data contracts and serialization |
| **Settings Management** | **pydantic-settings 2.16.1** | Strongly-typed environment variables via `.env` |
| **Database Engine** | **PostgreSQL (v18 / v16)** | Relational database with row-level concurrency locks |
| **Database Driver** | **asyncpg 0.32.0** | Native async driver (prepared statements, zero ORM overhead) |
| **Frontend Architecture**| **Vanilla ES6+ / HTML5 / CSS3**| No Node.js build step required; instant live-reload |
| **Typography & Styling** | **Cairo, Tajawal, Almarai** | Native Arabic font stack, CSS custom properties, RTL layout |
| **Testing Suite** | **pytest 9.1.1 + pytest-asyncio**| Asynchronous test runner with TestClient integration |

---

## 🚀 Key Verified Features

1. **Customer 360 & Anti-Duplication**: Unified profiles keyed on national ID/Iqama, mobile, or email; tracks past inquiries, viewing history, contracts, and financial receipts.
2. **Purpose-Based Lead Qualification**: Leads fork automatically into RENT, BUY, or INVEST pipelines upon qualification.
3. **Automated Workflow Engine (`WorkflowEngine`)**:
   - Automated first-contact task generation (30-minute SLA).
   - Standard Operating Procedure (SOP) step-by-step guidance for agents.
   - Dynamic outcome transitions triggering downstream jobs.
   - **Smart Reopen & Undo**: Safely reverts erroneously completed tasks and cascades rollbacks.
4. **48-Hour Reservation Lock & Gated Cancellation**:
   - Concurrency protection via row-level locks (`SELECT ... FOR UPDATE`).
   - Units are locked for 48 hours awaiting earnest deposit payment (`عربون`).
   - Gated deal cancellation: Deals with financial obligations or reserved units cannot be marked lost until remediation tasks (refunds, credit notes, unreserving units) are verified complete.
5. **Saudi Real Estate Financial Engine (`CalculationService`)**:
   - Real estate brokerage commissions: 2.5% statutory cap.
   - Value Added Tax (VAT): 15% on brokerage fees.
   - Real Estate Transaction Tax (RETT / ضريبة التصرفات العقارية): 5% on property purchases.
   - Agent compensation schemes: Salaried, Pure Commission, or Hybrid.
6. **Property Management & Maintenance**:
   - Tenancy contracts with scheduled rent installment generation.
   - Maintenance work orders, priority triage, vendor assignments, and expense tracking.
   - Periodic owner yield distributions and balance reconciliation.
7. **Official Document Generation (`DocumentTemplates`)**:
   - Authentic HTML documents for due diligence reports, Taqeem valuations, RETT tax notices, commercial offers, reservations, and ZATCA-compliant invoices.
8. **Role-Based Access Control (RBAC) & Scoping**:
   - Granular roles: `SYS_ADMIN`, `GENERAL_MANAGER`, `SALES_MANAGER`, `SALES_AGENT`, `LEASING_AGENT`, `ACCOUNTANT`, `PROPERTY_MANAGER`, `DOCUMENT_CONTROL`, `MARKETING`, `AUDITOR`.
   - Data scoping: `GLOBAL` (all records), `BRANCH` (branch records), and `OWN` (frontline agent records).

---

## 📁 Repository Structure

```text
RECRM/
├── Docs/                               # Legacy documentation and background blueprints
├── docs/                               # 18 Standardized Project Technical Documents
│   ├── 00_PROJECT_OVERVIEW.md
│   ├── 01_BEGINNER_DEVELOPER_GUIDE.md
│   ├── 02_TECHNOLOGY_STACK.md
│   ├── 03_ARCHITECTURE.md
│   ├── 04_PROJECT_FILE_MAP.md
│   ├── 05_MODULES_AND_FEATURES.md
│   ├── 06_BUSINESS_WORKFLOWS.md
│   ├── 07_FRONTEND_GUIDE.md
│   ├── 08_BACKEND_GUIDE.md
│   ├── 09_DATABASE_GUIDE.md
│   ├── 10_API_REFERENCE.md
│   ├── 11_AUTHENTICATION_AND_AUTHORIZATION.md
│   ├── 12_VALIDATION_AND_ERROR_HANDLING.md
│   ├── 13_SETUP_RUN_AND_TEST.md
│   ├── 14_SECURITY_REVIEW.md
│   ├── 15_CODE_REVIEW_REPORT.md
│   ├── 16_KNOWN_ISSUES_AND_RECOMMENDATIONS.md
│   └── 17_GLOSSARY.md
├── scripts/                            # Database migrations, seeders, and reset tools
│   ├── reset_database.py              # Operational data reset script
│   ├── migrate_cancellation_workflow.py
│   ├── migrate_stage2_schema.py
│   └── switch_db.py
├── src/
│   ├── backend/                        # FastAPI Application Core
│   │   ├── app/
│   │   │   ├── main.py                 # Application factory & router mount
│   │   │   ├── config.py               # Pydantic settings & database URLs
│   │   │   ├── database.py             # asyncpg connection pool & ID sequence generator
│   │   │   ├── routers/                # 16 API endpoints routers
│   │   │   ├── schemas/                # Pydantic request/response data contracts
│   │   │   └── services/               # WorkflowEngine, CalculationService, DocumentTemplates
│   │   ├── requirements.txt            # Python dependencies
│   │   └── run.py                      # Uvicorn entry point
│   └── ui/                             # Pure HTML5/CSS3/Vanilla JS Frontend
│       ├── index.html                  # Executive Dashboard
│       ├── customers.html              # Customer 360
│       ├── leads.html                  # Leads & Inquiries
│       ├── properties.html             # Property & Unit Inventory
│       ├── sales.html                  # Sales Pipeline & Deals Board
│       ├── finance.html                # Invoices, Payments & Commissions
│       ├── management.html             # Property Management & Maintenance
│       ├── tasks.html                  # Tasks, Activities & SOP Execution
│       ├── documents.html              # Document Repository & Print Previews
│       ├── campaigns.html              # Marketing & Ad Campaigns
│       ├── listings.html               # Real Estate Syndication
│       ├── admin.html                  # System Governance & RBAC
│       ├── common.js                   # Shared UI library (Toast, Modals, API helper)
│       └── user_session.js             # RBAC session & user switcher
├── tests/                              # 31 Pytest Test Suites (198 tests)
├── README.md                           # This document
├── start_server.sh                     # Automated application launcher script
├── stop_server.sh                      # Graceful server shutdown script
└── setup_new_laptop.sh                 # One-time developer environment setup
```

---

## ⚙️ Prerequisites

- **Operating System**: Linux (Ubuntu 22.04 / 24.04 LTS recommended), macOS, or Windows via WSL2.
- **Python**: Version `3.12` to `3.14` with `venv` and `pip`.
- **PostgreSQL**: Version `14` or newer (PostgreSQL 16 or 18 recommended) listening on port `5432`.
- **Tools**: `curl`, `git`, and a modern web browser (Google Chrome, Firefox, Safari, or Microsoft Edge).

---

## 📦 Installation & Setup

1. **Clone the Repository**:
   ```bash
   git clone <repository_url> RECRM
   cd RECRM
   ```

2. **Create and Activate Python Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r src/backend/requirements.txt
   ```

---

## 🔧 Environment Configuration

The application reads configuration from a `.env` file located in the project root. Create or update `.env`:

```ini
# Database Connection (PostgreSQL)
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_NAME=re_db

# API Server Settings
API_HOST=0.0.0.0
API_PORT=8000
API_PREFIX=/api/v1

# Environment Mode
ENVIRONMENT=development
DEBUG=True
```

---

## 🗄️ Database Initialization

1. **Create the Database in PostgreSQL**:
   ```bash
   psql -U postgres -h localhost -c "CREATE DATABASE re_db;"
   ```

2. **Run the Database Setup & Migration Scripts**:
   ```bash
   # Initialize tables, sequences, and seed core lookups
   PYTHONPATH=src/backend .venv/bin/python scripts/reset_database.py --mode crm --yes

   # Apply Stage 2 migrations (maintenance, tenancies, yield distributions)
   PYTHONPATH=src/backend .venv/bin/python scripts/migrate_stage2_schema.py

   # Apply Gated Cancellation workflow templates
   PYTHONPATH=src/backend .venv/bin/python scripts/migrate_cancellation_workflow.py
   ```

---

## ⚡ Running the Application

### Option A: The Fast All-in-One Launcher (Recommended)
Use the automated shell script which validates PostgreSQL, starts Uvicorn, and automatically opens your web browser:
```bash
./start_server.sh
```

**Options for `start_server.sh`**:
- `./start_server.sh --daemon`: Runs the server as a background service.
- `./start_server.sh --status`: Checks health of PostgreSQL and the FastAPI server.
- `./start_server.sh --stop`: Gracefully stops any running instance.
- `./start_server.sh --restart`: Restarts the service.

### Option B: Manual CLI Execution
```bash
source .venv/bin/activate
export PYTHONPATH=src/backend
python src/backend/run.py
```

### Accessing the System
- **Executive Dashboard**: [http://localhost:8000/ui/index.html](http://localhost:8000/ui/index.html)
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc API Reference**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🧪 Running Tests

The test suite runs against the live local database with strict test isolation and automated database hygiene (zero orphaned test records).

To run all 198 tests:
```bash
PYTHONPATH=src/backend .venv/bin/pytest tests/ -v
```

To run a specific test suite:
```bash
# Saudi Fee Calculations & Invoicing
PYTHONPATH=src/backend .venv/bin/pytest tests/test_saudi_fees_and_invoices.py -v

# Gated Cancellation & Remediation Workflows
PYTHONPATH=src/backend .venv/bin/pytest tests/test_cancellation_workflows.py -v

# Property Management & Maintenance Operations
PYTHONPATH=src/backend .venv/bin/pytest tests/test_stage2_operations.py -v

# Role-Based Scoping & Security
PYTHONPATH=src/backend .venv/bin/pytest tests/test_rbac_and_scoping.py -v
```

---

## 📚 Documentation Directory

Explore the complete technical and operational documentation in the [`docs/`](file:///home/nemro/RECRM/docs) folder:

| Document | Title | Description |
|---|---|---|
| [`00_PROJECT_OVERVIEW.md`](file:///home/nemro/RECRM/docs/00_PROJECT_OVERVIEW.md) | Project Overview | Non-technical explanation of business goals and architecture |
| [`01_BEGINNER_DEVELOPER_GUIDE.md`](file:///home/nemro/RECRM/docs/01_BEGINNER_DEVELOPER_GUIDE.md) | Beginner Developer Guide | Educational handbook explaining this codebase's mechanics |
| [`02_TECHNOLOGY_STACK.md`](file:///home/nemro/RECRM/docs/02_TECHNOLOGY_STACK.md) | Technology Stack | Detailed inventory of languages, frameworks, and packages |
| [`03_ARCHITECTURE.md`](file:///home/nemro/RECRM/docs/03_ARCHITECTURE.md) | System Architecture | Architecture diagrams, request flows, and state machines |
| [`04_PROJECT_FILE_MAP.md`](file:///home/nemro/RECRM/docs/04_PROJECT_FILE_MAP.md) | Project File Map | Comprehensive map of every file, function, and responsibility |
| [`05_MODULES_AND_FEATURES.md`](file:///home/nemro/RECRM/docs/05_MODULES_AND_FEATURES.md) | Modules & Features | Detailed status and specifications for all 12 modules |
| [`06_BUSINESS_WORKFLOWS.md`](file:///home/nemro/RECRM/docs/06_BUSINESS_WORKFLOWS.md) | Business Workflows | End-to-end operational workflows with Mermaid flowcharts |
| [`07_FRONTEND_GUIDE.md`](file:///home/nemro/RECRM/docs/07_FRONTEND_GUIDE.md) | Frontend Guide | UI components, design tokens, DOM state, and i18n |
| [`08_BACKEND_GUIDE.md`](file:///home/nemro/RECRM/docs/08_BACKEND_GUIDE.md) | Backend Guide | FastAPI routing, dependency injection, and service layers |
| [`09_DATABASE_GUIDE.md`](file:///home/nemro/RECRM/docs/09_DATABASE_GUIDE.md) | Database Guide | 53-table relational schema, sequences, and entity diagrams |
| [`10_API_REFERENCE.md`](file:///home/nemro/RECRM/docs/10_API_REFERENCE.md) | API Reference | Exhaustive reference for all REST endpoints and payloads |
| [`11_AUTHENTICATION_AND_AUTHORIZATION.md`](file:///home/nemro/RECRM/docs/11_AUTHENTICATION_AND_AUTHORIZATION.md) | Auth & Scoping Guide | RBAC roles, permission codes, and data scoping filters |
| [`12_VALIDATION_AND_ERROR_HANDLING.md`](file:///home/nemro/RECRM/docs/12_VALIDATION_AND_ERROR_HANDLING.md) | Validation & Errors | 4-layer validation strategy and standardized error envelopes |
| [`13_SETUP_RUN_AND_TEST.md`](file:///home/nemro/RECRM/docs/13_SETUP_RUN_AND_TEST.md) | Setup, Run & Test Guide | Step-by-step developer guide with troubleshooting tips |
| [`14_SECURITY_REVIEW.md`](file:///home/nemro/RECRM/docs/14_SECURITY_REVIEW.md) | Security Review | Security audit, vulnerability assessment, and hardening plan |
| [`15_CODE_REVIEW_REPORT.md`](file:///home/nemro/RECRM/docs/15_CODE_REVIEW_REPORT.md) | Code Review Report | Consolidated code review organized by severity |
| [`16_KNOWN_ISSUES_AND_RECOMMENDATIONS.md`](file:///home/nemro/RECRM/docs/16_KNOWN_ISSUES_AND_RECOMMENDATIONS.md) | Improvement Roadmap | Prioritized engineering recommendations for future sprints |
| [`17_GLOSSARY.md`](file:///home/nemro/RECRM/docs/17_GLOSSARY.md) | Developer & Business Glossary | Key terms explained for beginner engineers |

