# 03. System Architecture Specification
### توثيق المعمارية العامة للنظام وتدفق العمليات والبيانات

This document provides a detailed architectural specification of the **RECRM** platform, covering its frontend, backend, database layers, communication patterns, state machines, and concurrency controls.

---

## 1. High-Level Architecture Diagram

RECRM is designed as a modular, monolithic asynchronous application. It combines a static multi-portal browser frontend with an asynchronous Python API engine connected directly to a relational PostgreSQL database.

```mermaid
graph TD
    subgraph ClientBrowser ["Client Web Browser (Desktop & Mobile)"]
        UI_Dash["Dashboard (index.html)"]
        UI_Sales["Sales Pipeline (sales.html)"]
        UI_Tasks["Tasks & SOPs (tasks.html)"]
        UI_Portals["Other 9 Portals (Leads, Customers, Finance...)"]
        CommonJS["common.js (Toasts, Modals, API Helpers)"]
        UserSession["user_session.js (RBAC & Active Context)"]
        
        UI_Dash --- CommonJS
        UI_Sales --- CommonJS
        UI_Tasks --- CommonJS
        UI_Portals --- CommonJS
        CommonJS --- UserSession
    end

    subgraph FastAPIServer ["FastAPI Asynchronous Application (Port 8000)"]
        Uvicorn["Uvicorn ASGI Server"]
        MW_Sec["Middleware: Correlation ID & Security Headers"]
        StaticMount["StaticFiles: Mounted at /ui"]
        
        subgraph APIRouters ["16 Modular API Routers (/api/v1)"]
            R_Auth["auth.py & reference.py"]
            R_Sales["sales.py & leads.py"]
            R_Comms["communications.py & tasks"]
            R_Finance["finance.py & management.py"]
            R_Docs["documents.py & investment.py"]
            R_Admin["admin.py & reports.py"]
        end
        
        subgraph ServiceLayer ["Domain Services & Business Engine"]
            WF["WorkflowEngine (State Machine & SOPs)"]
            Calc["CalculationService (Saudi Formulas & RETT)"]
            DocGen["DocumentTemplates (HTML Rendering)"]
        end

        subgraph BackgroundWorkers ["Background Asynchronous Tasks"]
            Worker_Res["reservation_expiry_worker (Runs every 60s)"]
        end
        
        DBPool["asyncpg Connection Pool (min: 2, max: 20)"]
    end

    subgraph DatabaseLayer ["PostgreSQL 18 Database (re_db: 5432)"]
        Tables_Core["Core Lookups & Users (users, roles, permissions, branches)"]
        Tables_CRM["Operational CRM (customers, leads, opportunities)"]
        Tables_Inv["Inventory (units, buildings, projects, listings)"]
        Tables_Tx["Transactions (viewings, offers, reservations, contracts, invoices)"]
        Tables_WF["Workflow Engine (tasks, activities, workflow_templates, SOPs)"]
        Sequences["45 Database Sequences (seq_*_id)"]
    end

    ClientBrowser -->|HTTP GET /ui/*.html| StaticMount
    ClientBrowser -->|REST API Requests JSON with X-User-ID| Uvicorn
    Uvicorn --> MW_Sec
    MW_Sec --> APIRouters
    APIRouters --> ServiceLayer
    APIRouters --> DBPool
    ServiceLayer --> DBPool
    Worker_Res --> DBPool
    DBPool --> DatabaseLayer
```

---

## 2. Frontend Architectural Pattern

Unlike single-page application (SPA) frameworks that package the entire application into a massive JavaScript bundle (such as Webpack or Vite), RECRM uses a **Multi-Portal Static Architecture**:
1. **Isolated HTML Portals**: Each business domain has its own dedicated HTML file in [`src/ui/`](file:///home/nemro/RECRM/src/ui) (e.g. `leads.html`, `sales.html`, `tasks.html`, `management.html`).
2. **Shared Foundation Libraries**:
   - [`common.js`](file:///home/nemro/RECRM/src/ui/common.js): Provides unified `apiRequest()` network calls, standard Toast notifications, confirmation modals, number formatting (`formatSAR()`), and date formatters.
   - [`user_session.js`](file:///home/nemro/RECRM/src/ui/user_session.js): Intercepts page loads to enforce Role-Based Access Control (RBAC), manages the active user session in `localStorage`, injects the `X-User-ID` header into all network requests, and renders the user switcher widget.
3. **State Management**:
   - **URL Query Parameters**: High-level context (such as `opportunity_id=opportunity-45` or `search=lead-102`) is mirrored in the browser address bar for shareable deep-linking.
   - **DOM State**: Filter states, tab selections, and modal inputs are stored directly in DOM elements, eliminating complex client-side reactive store synchronization issues.
   - **Local Storage**: Stores user preferences, current language selection (`currentLang: 'ar' | 'en'`), and selected employee identity.

---

## 3. Backend Architectural Pattern

The backend follows a **Layered Asynchronous Architecture**:

```
HTTP Request ➔ Middleware ➔ Router (Controller) ➔ Service Layer ➔ asyncpg Pool ➔ PostgreSQL
```

### Layer 1: Middleware & Lifespan
- **Lifespan Manager** ([`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L38)): Manages application startup and shutdown. On startup, it establishes the asyncpg database connection pool (`init_db_pool()`) and spawns the background reservation expiry worker. On shutdown, it cancels workers and closes all database sockets cleanly.
- **Security & Correlation Middleware** ([`main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L73)): Injects a unique `X-Request-ID` into every request/response cycle, sets standard security headers (`nosniff`, `SAMEORIGIN`, `strict-origin-when-cross-origin`), and enforces cache-busting headers on UI assets.

### Layer 2: API Routers (Controllers)
- 16 discrete routers in [`src/backend/app/routers/`](file:///home/nemro/RECRM/src/backend/app/routers).
- Each router endpoint uses FastAPI's `Depends(get_db)` to acquire a dedicated connection from the connection pool for the lifetime of that request.
- Handles input parsing via Pydantic schemas, permission verification, and scope filtering (`resolve_data_scope_filter`).

### Layer 3: Domain Services
- **`WorkflowEngine`** ([`src/backend/app/services/workflow_engine.py`](file:///home/nemro/RECRM/src/backend/app/services/workflow_engine.py)): Central state machine that enforces standard operating procedures, chains dependent tasks, handles smart reopen/undo, checks SLAs, and manages gated cancellations.
- **`CalculationService`** ([`src/backend/app/services/calculation_service.py`](file:///home/nemro/RECRM/src/backend/app/services/calculation_service.py)): Implements pure business math: Saudi brokerage commissions (2.5%), VAT (15%), RETT (5%), Net Operating Income (NOI), Cap Rates, and multi-factor property matching scores.
- **`DocumentTemplates`** ([`src/backend/app/services/document_templates.py`](file:///home/nemro/RECRM/src/backend/app/services/document_templates.py)): Formats and renders official Saudi real estate documents into clean, print-ready HTML documents.

### Layer 4: Data Access Layer
- Raw asynchronous SQL queries using **`asyncpg`**.
- Explicit transaction handling via `async with conn.transaction():`.
- Zero ORM impedance mismatch; queries take full advantage of PostgreSQL native features (prepared statements, sequences, JSONB operators, and CTEs).

---

## 4. End-to-End Request Flow: Unit Reservation & Concurrency Lock

The diagram below illustrates how RECRM protects against double-booking when an agent reserves a property unit:

```mermaid
sequenceDiagram
    autonumber
    actor Agent as Sales Agent
    participant UI as sales.html
    participant Router as sales.py
    participant WF as WorkflowEngine
    participant DB as PostgreSQL (re_db)

    Agent->>UI: Selects Unit & Clicks "Reserve Unit"
    UI->>Router: POST /api/v1/opportunities/{opp_id}/reserve (unit_id, deposit_amount)
    Router->>DB: Begin Transaction (async with conn.transaction())
    Router->>WF: create_unit_reservation(conn, opp_id, unit_id, ...)
    
    rect rgb(255, 243, 205)
        Note over WF,DB: Concurrency Protection (Row-Level Lock)
        WF->>DB: SELECT status FROM units WHERE unit_id = $1 FOR UPDATE
        alt Unit status != 'AVAILABLE'
            DB-->>WF: status is 'RESERVED' or 'SOLD'
            WF-->>Router: Raise ValueError("Unit is no longer available")
            Router-->>UI: HTTP 400 Bad Request
            UI-->>Agent: Shows error toast: Unit already reserved by another agent
        end
    end

    WF->>DB: UPDATE units SET status = 'RESERVED' WHERE unit_id = $1
    WF->>DB: INSERT INTO unit_status_history (unit_id, old_status, new_status, reason)
    WF->>DB: INSERT INTO reservations (..., deposit_amount, status='ACTIVE', expires_at = NOW() + 48h)
    WF->>DB: INSERT INTO tasks (template_id='TASK_RESERVATION_DEPOSIT_COLLECTION', due_at = NOW() + 48h)
    WF->>DB: INSERT INTO activities (template_id='ACT_UNIT_RESERVED')
    Router->>DB: Commit Transaction
    Router-->>UI: HTTP 201 Created (Reservation Details & 48h SLA timer)
    UI-->>Agent: Displays green confirmation toast & locks unit on board
```

---

## 5. Workflow State Machine Architecture

The lifecycle of any real estate transaction in RECRM is driven by a deterministic state machine governed by `workflow_templates` and `workflow_sop_guidance`.

```mermaid
stateDiagram-v2
    [*] --> NEW_LEAD: Customer Inquires (Portal / Phone)
    
    NEW_LEAD --> QUALIFIED: TASK_FIRST_CONTACT completed (Connected & Qualified)
    NEW_LEAD --> LOST: TASK_FIRST_CONTACT cancelled / Unreachable
    
    state QUALIFIED {
        [*] --> FORK_PURPOSE
        FORK_PURPOSE --> RENT_PATH: Purpose = RENT
        FORK_PURPOSE --> BUY_PATH: Purpose = BUY
        FORK_PURPOSE --> INVEST_PATH: Purpose = INVEST
    }
    
    QUALIFIED --> VIEWING: Property Matched & Viewing Scheduled
    VIEWING --> OFFER: Viewing Completed & Client Submits Offer
    
    state OFFER {
        [*] --> OFFER_SUBMITTED
        OFFER_SUBMITTED --> NEGOTIATION: Counter-Offer from Landlord/Seller
        NEGOTIATION --> OFFER_ACCEPTED: Agreed Terms
    }
    
    OFFER --> RESERVATION: Unit Reserved (48h Earnest Deposit SLA)
    
    state RESERVATION {
        [*] --> AWAITING_DEPOSIT: Unit Locked
        AWAITING_DEPOSIT --> DEPOSIT_PAID: SADA / Wire Verified
        AWAITING_DEPOSIT --> AUTO_EXPIRED: 48h SLA breached (Unit Released)
    }
    
    RESERVATION --> CONTRACT_DRAFT: Contract Preparation (Ejar / Sale)
    CONTRACT_DRAFT --> FEES_INVOICED: 2.5% Brokerage + 15% VAT Invoiced
    FEES_INVOICED --> CLOSED_WON: Fees Paid & Contract Fully Signed
    
    state CANCELLATION_GATING {
        [*] --> UNDER_CANCELLATION: Cancellation Initiated
        UNDER_CANCELLATION --> TASK_FIN_SETTLE: Remediate Invoices / Refunds
        UNDER_CANCELLATION --> TASK_INV_RELEASE: Release Unit back to AVAILABLE
        TASK_FIN_SETTLE --> CHECK_READY: Task Completed
        TASK_INV_RELEASE --> CHECK_READY: Task Completed
        CHECK_READY --> CLOSED_LOST: Zero Open Remediation Tasks Remain
    }

    QUALIFIED --> CANCELLATION_GATING: Cancellation Requested
    VIEWING --> CANCELLATION_GATING: Cancellation Requested
    OFFER --> CANCELLATION_GATING: Cancellation Requested
    RESERVATION --> CANCELLATION_GATING: Cancellation Requested
```

---

## 6. Gated Deal Cancellation & Remediation Architecture

A key architectural rule enforced by RECRM is that **a deal cannot be marked lost or cancelled while financial or asset commitments remain unresolved**:

1. **Obligation Analysis**:
   - The system checks `invoices` for unpaid/active bills.
   - The system checks `reservations` for active unit holds and deposited money (`عربون`).
   - The system checks `opportunity_units` for units held in `RESERVED` status.
2. **Forking Logic**:
   - If **zero obligations exist**: The deal moves immediately to `CLOSED_LOST` and linked leads move to `LOST`.
   - If **obligations exist**:
     - The opportunity transitions to **`UNDER_CANCELLATION`**.
     - Open operational forward tasks are automatically cancelled.
     - Two mandatory remediation tasks are spawned:
       * `TASK_DEAL_FINANCIAL_SETTLEMENT` (Assigned to Accountant, 48h SLA): Audit invoices, issue credit notes, return deposits.
       * `TASK_DEAL_INVENTORY_RELEASE` (Assigned to Sales Agent, 12h SLA): Release unit hold back to `AVAILABLE`.
     - Direct `PATCH` requests to `CLOSED_LOST` are blocked with `HTTP 400`.
3. **Automated Finalization**:
   - When each remediation task is completed via `complete_task_with_outcome`, the engine verifies whether any open remediation tasks remain.
   - When the count reaches zero, the system automatically finalizes the deal to `CLOSED_LOST` and updates the linked lead to `LOST`.

---

## 7. Data Scoping & Authorization Architecture

Data visibility in RECRM follows a hierarchical scoping model resolved dynamically on every query:

```mermaid
graph TD
    subgraph Roles ["User Role Categories"]
        R_Exec["Executive / Governance: SYS_ADMIN, GENERAL_MANAGER, AUDITOR"]
        R_Branch["Branch Leadership: SALES_MANAGER, BRANCH_MANAGER"]
        R_Front["Frontline Agents: SALES_AGENT, LEASING_AGENT"]
    end

    subgraph ScopeEngine ["Scope Resolution Engine (auth.py: resolve_data_scope_filter)"]
        S_Global["Scope: GLOBAL (No WHERE user filter applied)"]
        S_Branch["Scope: BRANCH (WHERE branch_id = user.branch_id)"]
        S_Own["Scope: OWN (WHERE assigned_user_id = user.user_id)"]
    end

    R_Exec --> S_Global
    R_Branch --> S_Branch
    R_Front --> S_Own

    S_Global --> Query["SQL Query Execution with asyncpg"]
    S_Branch --> Query
    S_Own --> Query
```

- **Frontline Agent Isolation**: When an agent with `OWN` scope calls `/api/v1/leads` or `/api/v1/tasks`, `resolve_data_scope_filter` forces the query parameter to their own `user_id`. Even if the agent maliciously tampers with the query string (e.g. `?assigned_user_id=user-99`), the backend strictly overrides it and restricts rows to their own assignments.
- **Branch Manager Visibility**: A manager in Jeddah automatically sees all leads, opportunities, and viewings belonging to agents in the Jeddah branch, but cannot see records belonging to the Riyadh or Medina branches unless granted global executive privileges.

