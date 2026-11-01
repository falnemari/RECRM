# Backend Developer Guide

> **Audience**: Backend developers, full-stack engineers, and API integrators.  
> **Scope**: Application lifecycle, dependency injection, pure-SQL asyncpg database layer, service architecture, background workers, and step-by-step backend maintenance workflows.

---

## 1. Architectural Philosophy & Technology Stack

The RECRM backend is a high-performance, asynchronous REST API built with modern Python.

```
                      +---------------------------------------+
                      |       Client / Frontend Request       |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       Uvicorn (ASGI Web Server)       |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     FastAPI Application (main.py)     |
                      |   - Correlation ID & Security Headers |
                      |   - CORS Middleware                   |
                      |   - ErrorEnvelope Exception Handlers  |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |      16 API Routers (/api/v1/*)       |
                      |   - Pydantic Schema Validation        |
                      |   - Dependency Injection: get_db      |
                      |   - RBAC & Scope Filtering            |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |             Service Layer             |
                      |   - WorkflowEngine (State & SOP)      |
                      |   - CalculationService (ZATCA/REGA)   |
                      |   - DocumentTemplates (HTML render)   |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |    Database Layer (asyncpg Pool)      |
                      |   - Pure Parameterized SQL Queries    |
                      |   - Row Locking (SELECT FOR UPDATE)   |
                      |   - Sequence Generators (get_next_id) |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |    PostgreSQL Database (re_db:5432)   |
                      +---------------------------------------+
```

### Key Architectural Decisions:
1. **Async / Await End-to-End**: Every route, database query, and service function uses Python's `asyncio` event loop for non-blocking I/O.
2. **Pure SQL with `asyncpg` (Zero ORM)**:
   - *Why no SQLAlchemy or Django ORM?* Pure SQL gives complete control over PostgreSQL-specific features like `SELECT ... FOR UPDATE`, transactional row locks, `RETURNING` clauses, complex `JOIN`s, and `json_build_object()`.
   - Performance is up to 3x–5x faster than heavy ORMs because there is no Python object hydration overhead.
3. **Pydantic V2 for Validation & Serialization**: Enforces strict typing, automatic data coercion, and descriptive validation error messages for all incoming requests.

---

## 2. Application Entry Point & Lifespan (`main.py`)

The application entry point is [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py).

### 2.1. Lifespan Context Manager
FastAPI uses modern Starlette `lifespan` handlers to manage startup and shutdown events:

```python
# From src/backend/app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Initialize asyncpg connection pool
    await init_db_pool()
    
    # 2. Startup: Launch background reservation auto-expiry worker
    worker_task = asyncio.create_task(reservation_expiry_worker())
    
    yield  # Application serves incoming HTTP requests
    
    # 3. Shutdown: Cancel background tasks cleanly
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
        
    # 4. Shutdown: Drain and close database connection pool
    await close_db_pool()
```

### 2.2. Middleware Stack
1. **CORS Middleware**: Allows cross-origin requests from development servers or external microservices.
2. **Correlation ID & Security Headers Middleware (`add_correlation_id_and_security_headers`)**:
   - Extracts incoming `X-Request-ID` or generates a fresh `uuid4`.
   - Binds `request_id` to `request.state.request_id` for downstream logging.
   - Attaches security headers to every response:
     - `X-Content-Type-Options: nosniff`
     - `X-Frame-Options: SAMEORIGIN`
     - `Referrer-Policy: strict-origin-when-cross-origin`
     - `X-XSS-Protection: 1; mode=block`
   - Injects `Cache-Control: no-cache` for all `/ui` static assets to ensure clients always see fresh code.

### 2.3. Standardized Error Handling
Any `RequestValidationError` (such as missing required fields or invalid data types) is intercepted by a custom exception handler and formatted into a unified response schema:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "request_id": "b78d2e8e-4a6f-45c1-92b0-8c2cb57f1234",
    "fields": {
      "phone": ["Field is required"],
      "budget_max": ["Input should be greater than 0"]
    }
  }
}
```

---

## 3. Database Layer & Dependency Injection

The database connection layer is implemented in [`src/backend/app/database.py`](file:///home/nemro/RECRM/src/backend/app/database.py).

### 3.1. Connection Pool (`asyncpg.create_pool`)
```python
pool = await asyncpg.create_pool(
    user=settings.DB_USER,
    password=settings.DB_PASSWORD,
    host=settings.DB_HOST,
    port=settings.DB_PORT,
    database=settings.DB_NAME,
    min_size=2,
    max_size=20,
    command_timeout=60,
)
```
- **Connection Reuse**: Instead of opening a new TCP socket per request, connections are pooled and shared across requests.
- **Automatic Lifecycle**: Connections are acquired, used, and automatically returned to the pool when the request ends.

### 3.2. Route Dependency: `get_db`
In your FastAPI route functions, declare `conn: asyncpg.Connection = Depends(get_db)`:

```python
from fastapi import APIRouter, Depends
import asyncpg
from app.database import get_db

router = APIRouter()

@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow(
        "SELECT * FROM leads WHERE lead_id = $1", 
        lead_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return dict(row)
```

### 3.3. Sequential ID Generation: `get_next_id`
All primary keys in RECRM follow human-readable alphanumeric formats (`cust-101`, `lead-205`, `prop-12`, `opp-45`). These are generated using PostgreSQL sequences:

```python
async def get_next_id(conn: asyncpg.Connection, table_name: str, prefix: str) -> str:
    seq_name = f"seq_{table_name}_id"
    val = await conn.fetchval(f"SELECT nextval('{seq_name}')")
    return f"{prefix}-{val}"
```

---

## 4. The 16 Backend Routers

Every router is located in `src/backend/app/routers/` and mounted under the `/api/v1` prefix:

| Router Module | Mount Prefix | Purpose & Business Domain |
|---|---|---|
| [`auth.py`](file:///home/nemro/RECRM/src/backend/app/routers/auth.py) | `/api/v1/auth` | User sessions, active user switcher, RBAC profile retrieval, scoping resolution. |
| [`reference.py`](file:///home/nemro/RECRM/src/backend/app/routers/reference.py) | `/api/v1/reference` | Lookup catalogs: Saudi cities, districts, property types, lead sources, task templates. |
| [`leads.py`](file:///home/nemro/RECRM/src/backend/app/routers/leads.py) | `/api/v1/leads` | Lead intake, qualification branching, lead assignments, contact verification. |
| [`customers.py`](file:///home/nemro/RECRM/src/backend/app/routers/customers.py) | `/api/v1/customers` | Customer 360, National ID/CR storage, KYC/AML risk assessment, client history. |
| [`properties.py`](file:///home/nemro/RECRM/src/backend/app/routers/properties.py) | `/api/v1/properties` | Property developments, individual units, unit reservation status, multi-unit matching. |
| [`sales.py`](file:///home/nemro/RECRM/src/backend/app/routers/sales.py) | `/api/v1/sales` | Deals & Opportunities, 48-hour reservations, viewings, gated deal cancellation. |
| [`management.py`](file:///home/nemro/RECRM/src/backend/app/routers/management.py) | `/api/v1/management` | Property management contracts, unit leases, rent schedules, maintenance work orders. |
| [`reports.py`](file:///home/nemro/RECRM/src/backend/app/routers/reports.py) | `/api/v1/reports` | Executive dashboards, sales conversion funnels, broker revenue, vacancy rates, operational calendar organizer (`/agenda-calendar`), and financial dues schedule (`/financial-schedule`). |
| [`finance.py`](file:///home/nemro/RECRM/src/backend/app/routers/finance.py) | `/api/v1/finance` | Tax invoices (2.5% fee + 15% VAT + 5% RETT), payment receipts, broker commissions. |
| [`communications.py`](file:///home/nemro/RECRM/src/backend/app/routers/communications.py) | `/api/v1/communications` | System notifications, SMS dispatch records, WhatsApp interactions, activity feed. |
| [`documents.py`](file:///home/nemro/RECRM/src/backend/app/routers/documents.py) | `/api/v1/documents` | Deed scans, lease PDF uploads, file metadata, document status validation. |
| [`marketing.py`](file:///home/nemro/RECRM/src/backend/app/routers/marketing.py) | `/api/v1/marketing` | Ad campaigns (Snapchat, Google Ads, Meta), marketing budgets, lead attribution tags. |
| [`listings.py`](file:///home/nemro/RECRM/src/backend/app/routers/listings.py) | `/api/v1/listings` | REGA public marketing listings, FAL license numbers, advertising compliance. |
| [`admin.py`](file:///home/nemro/RECRM/src/backend/app/routers/admin.py) | `/api/v1/admin` | System user CRUD, role management, branch creation, comprehensive audit log viewer. |
| [`calculations.py`](file:///home/nemro/RECRM/src/backend/app/routers/calculations.py) | `/api/v1/calculations` | Financial calculators: Statutory fees, ROI, Net Operating Income (NOI), Cap Rate. |
| [`investment.py`](file:///home/nemro/RECRM/src/backend/app/routers/investment.py) | `/api/v1/investment` | Investment due diligence: multi-tenant lease verification, expense audits, valuation models. |

---

## 5. Domain Service Layer

Business logic is encapsulated inside specialized service classes in `src/backend/app/services/`:

### 5.1. `WorkflowEngine` (`workflow_engine.py`)
The operational backbone of the CRM (over 8,000 lines of state machine logic):
- **Dynamic Task Creation**: Creates downstream tasks automatically when triggers fire (e.g., qualifying a lead automatically spawns `TASK_INITIAL_CALL`).
- **SOP Checklist Enforcement**: Validates that all required operational items (e.g., verifying title deed, checking lease contracts) are completed before a task can be marked `COMPLETED`.
- **48-Hour Reservation Expiry**: Releases unit locks and cancels unpaid reservations automatically.
- **Smart Task Reopen**: Allows reopening a completed task while tracking modification reasons and recalculating opportunity stage progression.
- **Gated Deal Cancellation**: Prevents deals from being cancelled until all pending earnest money, statutory invoices, and external fees are resolved or refunded.

### 5.2. `CalculationService` (`calculation_service.py`)
Encapsulates real estate financial mathematics according to Saudi law:
- **Statutory Brokerage Fee**: `property_price * 0.025` (capped at 2.5% pursuant to REGA regulations).
- **Value Added Tax (VAT)**: `brokerage_fee * 0.15` (15% ZATCA tax applied to services).
- **Real Estate Transaction Tax (RETT / ضريبة التصرفات العقارية)**: `property_price * 0.05` (5% government transfer tax).
- **Net Operating Income (NOI)**: `Gross Rental Revenue - Operating Expenses (OPEX)`.
- **Capitalization Rate (Cap Rate)**: `(NOI / Property Purchase Price) * 100`.

### 5.3. `DocumentTemplates` (`document_templates.py`)
Generates standardized, print-ready HTML documents:
- Official Brokerage Representation Agreement (عقد وساطة عقارية).
- Unit Reservation Agreement (سند حجز مبدئي).
- Tax Invoices conforming to ZATCA Phase 1 & Phase 2 layout requirements.

---

## 6. Background Workers & Concurrency

### 6.1. Reservation Expiry Worker
Defined in `src/backend/app/main.py`:
- Runs an infinite loop waking every 60 seconds.
- Acquires a connection from `pool` and calls `WorkflowEngine.process_expired_reservations(conn)`.
- Checks for reservations where `status = 'ACTIVE'` and `deposit_status = 'PENDING'` and `expires_at < NOW()`.
- Automatically transitions reservation to `EXPIRED`, resets the unit status from `RESERVED` back to `AVAILABLE`, and records an audit log.

### 6.2. Concurrency Control with `SELECT ... FOR UPDATE`
When reserving a unit or modifying a financial ledger, RECRM avoids race conditions by acquiring a database row lock:

```python
async with conn.transaction():
    # Row is locked against concurrent transactions until this block exits
    unit = await conn.fetchrow(
        "SELECT unit_id, status FROM units WHERE unit_id = $1 FOR UPDATE",
        unit_id
    )
    if unit["status"] != "AVAILABLE":
        raise HTTPException(status_code=400, detail="Unit is no longer available")
        
    await conn.execute(
        "UPDATE units SET status = 'RESERVED' WHERE unit_id = $1", 
        unit_id
    )
```

---

## 7. Beginner Developer Cheatsheet for Backend

### Recipe 1: How to Add a New GET API Endpoint
**Goal**: Add an endpoint `GET /api/v1/properties/{property_id}/stats` returning the count of available vs occupied units.

1. Open `src/backend/app/routers/properties.py`.
2. Add your route handler:

```python
@router.get("/{property_id}/stats", response_model=ResponseEnvelope[dict])
async def get_property_unit_stats(
    property_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    stats = await conn.fetchrow(
        """
        SELECT 
            COUNT(*) as total_units,
            COUNT(*) FILTER (WHERE status = 'AVAILABLE') as available_units,
            COUNT(*) FILTER (WHERE status = 'OCCUPIED') as occupied_units,
            COUNT(*) FILTER (WHERE status = 'RESERVED') as reserved_units
        FROM units
        WHERE property_id = $1
        """,
        property_id
    )
    
    if not stats or stats["total_units"] == 0:
        raise HTTPException(status_code=404, detail="Property not found or has no units")
        
    return ResponseEnvelope(
        data=dict(stats),
        meta=BaseMeta(total=1)
    )
```

---

### Recipe 2: How to Add a Transactional POST Endpoint
**Goal**: Record a payment against an invoice and update the invoice balance safely.

```python
@router.post("/invoices/{invoice_id}/payments")
async def record_payment(
    invoice_id: str,
    payload: PaymentCreateIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header("user-51")
):
    async with conn.transaction():
        # 1. Lock invoice row
        invoice = await conn.fetchrow(
            "SELECT total_amount, paid_amount, status FROM invoices WHERE invoice_id = $1 FOR UPDATE",
            invoice_id
        )
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
            
        new_paid = float(invoice["paid_amount"]) + float(payload.amount)
        new_status = "PAID" if new_paid >= float(invoice["total_amount"]) else "PARTIALLY_PAID"
        
        # 2. Insert payment record
        payment_id = await get_next_id(conn, "payments", "pay")
        await conn.execute(
            """
            INSERT INTO payments (payment_id, invoice_id, amount, payment_method, recorded_by, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            payment_id, invoice_id, payload.amount, payload.payment_method, x_user_id
        )
        
        # 3. Update invoice balance
        await conn.execute(
            "UPDATE invoices SET paid_amount = $1, status = $2, updated_at = NOW() WHERE invoice_id = $3",
            new_paid, new_status, invoice_id
        )
        
    return {"status": "SUCCESS", "payment_id": payment_id, "new_invoice_status": new_status}
```

---

## 8. Summary Checklist for Backend Changes

- [ ] Use `Depends(get_db)` to acquire connections—never instantiate raw connections manually.
- [ ] Always parameterize SQL queries with `$1`, `$2`, etc. Never use Python f-strings to concatenate SQL variables (prevents SQL injection).
- [ ] For sequential IDs, use `await get_next_id(conn, table_name, prefix)`.
- [ ] Wrap multi-table modifications inside `async with conn.transaction():`.
- [ ] Use `SELECT ... FOR UPDATE` whenever checking and immediately updating status or balance.
- [ ] Ensure all responses conform to `ResponseEnvelope` or standard HTTP exception status codes.

