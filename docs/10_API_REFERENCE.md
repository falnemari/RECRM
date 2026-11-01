# API Reference Guide

> **Audience**: Full-stack engineers, frontend developers, and backend API integrators.  
> **Scope**: Complete REST API specifications across all 16 routers and 145 endpoints, request/response envelopes, authentication headers, error codes, and practical `curl` examples.

---

## 1. Global API Standards

- **Base URL**: `http://localhost:8000/api/v1`
- **Default Media Type**: `application/json; charset=utf-8`
- **Interactive Documentation**:
  - Swagger UI: `http://localhost:8000/docs`
  - ReDoc: `http://localhost:8000/redoc`
  - OpenAPI Specification: `http://localhost:8000/openapi.json`

### 1.1. Required Request Headers
| Header | Type | Required | Description | Example |
|---|---|---|---|---|
| `X-User-ID` | String | Recommended | Identifies the active user session for RBAC scoping and audit tracking. | `user-51` |
| `Content-Type` | String | Required for POST/PUT | Media type of the request payload. | `application/json` |
| `X-Request-ID` | String | Optional | Client correlation ID for tracing. System generates a `UUIDv4` if omitted. | `req-84c2-901b` |

### 1.2. Standard Response Envelope (`ResponseEnvelope[T]`)
Successful API responses return data wrapped inside a standardized structure:

```json
{
  "data": { ... },
  "meta": {
    "total": 45,
    "page": 1,
    "limit": 20,
    "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
  }
}
```

### 1.3. Standard Error Envelope (`ErrorEnvelope`)
Errors return HTTP 4xx or 5xx with a structured error detail:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more input fields are invalid.",
    "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "fields": {
      "budget_min": ["Budget min must be a positive integer."]
    }
  }
}
```

### 1.4. HTTP Status Code Conventions
| Status Code | Meaning | RECRM Scenario |
|---|---|---|
| `200 OK` | Successful request | Fetching lists, details, or successful computation. |
| `201 Created` | Successful creation | Entity created (`POST /leads`, `POST /tasks`). |
| `400 Bad Request` | Business rule violation | Transitioning to an illegal state or missing SOP item. |
| `401 Unauthorized` | Identity missing | User account disabled or invalid identifier. |
| `403 Forbidden` | Access denied | User data scope or role lacks required permission. |
| `404 Not Found` | Entity not found | Invalid `lead_id`, `opportunity_id`, or `unit_id`. |
| `409 Conflict` | Concurrency collision | Unit already reserved by another transaction. |
| `422 Unprocessable Entity` | Schema validation error | Missing required fields or schema mismatch. |
| `500 Internal Server Error` | Unhandled failure | Database connection failure or unhandled exception. |

---

## 2. Authentication & User Session (`/api/v1/auth`)

### `GET /api/v1/auth/me`
Retrieves the profile, assigned roles, permissions, and data scope of the current caller.

- **Headers**: `X-User-ID: user-51`
- **Response**: `200 OK`
```json
{
  "data": {
    "user_id": "user-51",
    "full_name": "Fahad Al-Nemari",
    "email": "fahad@recrm.sa",
    "branch_id": "branch-01",
    "roles": ["SYS_ADMIN"],
    "permissions": ["ADMIN", "LEAD_READ", "LEAD_WRITE", "SALES_WRITE"],
    "data_scope": "GLOBAL"
  }
}
```

### `GET /api/v1/auth/users`
Lists all active users in the brokerage to populate the frontend user switcher modal.

- **Response**: `200 OK` (Array of user records grouped by branch and role).

---

## 3. Lead Intake & Qualification (`/api/v1/leads`)

### `GET /api/v1/leads`
Lists leads with dynamic scoping and filtering.

- **Query Parameters**:
  - `status`: `NEW`, `CONTACTED`, `QUALIFIED`, `LOST`
  - `service_type`: `PURCHASE`, `RENT`, `INVESTMENT`
  - `assigned_user_id`: Filter by assigned broker
  - `branch_id`: Filter by branch
  - `limit`: Default `50`, max `200`
  - `offset`: Default `0`
- **Response**: `200 OK` with paginated lead items.

### `POST /api/v1/leads`
Creates an inbound lead and triggers automatic qualification tasks.

- **Payload**:
```json
{
  "first_name": "سعد",
  "last_name": "الغامدي",
  "phone": "+966501234567",
  "email": "saad@example.sa",
  "service_type": "PURCHASE",
  "property_type": "VILLA",
  "budget_min": 2000000,
  "budget_max": 2800000,
  "city_id": "city-01",
  "preferred_districts": ["dist-04", "dist-07"],
  "source_id": "src-meta-ads"
}
```
- **Response**: `201 Created`
```json
{
  "data": {
    "lead_id": "lead-182",
    "customer_id": "cust-94",
    "status": "NEW",
    "assigned_user_id": "user-52",
    "tasks_created": ["task-510"]
  }
}
```

### `POST /api/v1/leads/{lead_id}/qualify`
Converts a qualified lead into an active sales opportunity.

- **Payload**:
```json
{
  "qualification_outcome": "QUALIFIED_HOT",
  "notes": "Client has pre-approved bank mortgage and ready for immediate viewing."
}
```
- **Response**: `200 OK` returning created `opportunity_id` and initial pipeline stage.

---

## 4. Property Portfolio & Inventory (`/api/v1`)

### `GET /api/v1/projects`
Retrieves registered real estate development projects with aggregated building and unit metrics.

- **Query Parameters**:
  - `search`: Keyword matching Arabic name, English name, project ID, or city name.
  - `status`: `ACTIVE`, `COMPLETED`, `UNDER_CONSTRUCTION`, `PLANNED`
  - `city_id`: Filter by city
  - `page` / `page_size`: Pagination
- **Response**: `200 OK`
```json
{
  "data": [
    {
      "project_id": "project-2",
      "name_ar": "مشروع أبراج النرجس",
      "name_en": "Al Narges Towers",
      "city_id": "city-01",
      "city_name_ar": "الرياض",
      "developer_customer_id": "cust-25",
      "developer_name": "شركة التطوير العقاري المتقدمة",
      "status": "ACTIVE",
      "buildings_count": 2,
      "units_count": 24
    }
  ]
}
```

### `POST /api/v1/projects`
Creates a new real estate project.

- **Payload**:
```json
{
  "name_ar": "مشروع واحة الياسمين",
  "name_en": "Al Yasmin Oasis Project",
  "city_id": "city-01",
  "status": "ACTIVE"
}
```
- **Response**: `201 Created` with created `project_id`.

### `GET /api/v1/buildings`
Retrieves registered buildings and towers with parent project metadata and unit counts.

- **Query Parameters**:
  - `search`: Keyword matching building code, building name, or parent project name.
  - `project_id`: Filter by parent project
  - `page` / `page_size`: Pagination
- **Response**: `200 OK`
```json
{
  "data": [
    {
      "building_id": "building-1",
      "project_id": "project-1",
      "building_code": "BLD-0052",
      "name": "برج الياسمين الأول",
      "floors_count": 12,
      "project_name_ar": "مشروع الياسمين السكني",
      "project_name_en": "Al Yasmin Residential",
      "units_count": 8
    }
  ]
}
```

### `POST /api/v1/buildings`
Creates a new building under a project.

- **Payload**:
```json
{
  "project_id": "project-1",
  "building_code": "BLD-0053",
  "name": "برج الياسمين الثاني",
  "floors_count": 14
}
```
- **Response**: `201 Created` with created `building_id`.

### `GET /api/v1/units`
Lists individual property units with multi-criteria filtering, building/project associations, and classification-specific floor metrics (`floor_no` for units in buildings, `total_floors` for whole assets like villas, duplexes, buildings, townhouses, and hotels, and `building_floors_count` for parent building height).

- **Query Parameters**:
  - `search`: Unit number or project/building query
  - `project_id`: Filter by project
  - `building_id`: Filter by building
  - `status`: `AVAILABLE`, `RESERVED`, `SOLD`, `RENTED`
  - `listing_purpose`: `SALE`, `RENT`, `INVESTMENT`, `ALL`
  - `bedrooms`: e.g. `3`
  - `assigned_user_id`: Filter by assigned broker
- **Response**: `200 OK` with paginated unit list.

### `POST /api/v1/units`
Creates a new property unit under a building or directly under a project.

- **Payload**:
```json
{
  "project_id": "project-1",
  "building_id": "building-1",
  "unit_number": "APT-501",
  "property_type_id": "property_type-3",
  "floor_no": 5,
  "total_floors": null,
  "area_sqm": 165.0,
  "asking_price": 750000.0,
  "status": "AVAILABLE"
}
```
*Note: For standalone structures (Villas, Duplexes, Townhouses, Buildings, Hotels), set `building_id: null` and specify `total_floors`.*

- **Response**: `201 Created` with created `unit_id`, `building_name`, `building_code`, and `building_floors_count`.

### `POST /api/v1/properties/match-units`
Matches an open lead's criteria against the available unit inventory.

- **Payload**:
```json
{
  "property_type": "VILLA",
  "city_id": "city-01",
  "budget_min": 2000000,
  "budget_max": 2800000,
  "min_bedrooms": 4
}
```
- **Response**: `200 OK` returning matched units sorted by compatibility score.

---

## 5. Sales Pipeline & Deals (`/api/v1/opportunities`)

### `GET /api/v1/opportunities`
Retrieves deals in the sales pipeline for Kanban or tabular display.

- **Query Parameters**:
  - `stage`: `DISCOVERY`, `QUALIFICATION`, `UNIT_SELECTION`, `VIEWING`, `NEGOTIATION`, `RESERVATION`, `CONTRACT`, `WON`, `LOST`
  - `assigned_user_id`: Filter by broker
- **Response**: `200 OK` with opportunity records and monetary deal values.

### `POST /api/v1/opportunities/{opportunity_id}/reserve`
Creates a 48-hour temporary reservation locking a unit.

- **Payload**:
```json
{
  "unit_id": "unit-105",
  "earnest_money_amount": 50000,
  "payment_method": "BANK_TRANSFER",
  "notes": "48h reservation pending deposit verification."
}
```
- **Response**: `200 OK` with `reservation_id`, `expires_at` (48 hours from now), and updated unit status `RESERVED`.

### `POST /api/v1/opportunities/{opportunity_id}/cancel`
Cancels an opportunity via gated checks.

- **Payload**:
```json
{
  "cancellation_reason": "Buyer failed to secure mortgage approval",
  "refund_earnest_money": true
}
```
- **Response**: `200 OK` when remediation tasks succeed, or `400 Bad Request` if pending invoices or deposits prevent cancellation.

---

## 6. Financial Ledger & Invoicing (`/api/v1/invoices` & `/api/v1/finance`)

### `GET /api/v1/invoices`
Lists all ZATCA tax invoices and billing statements.

- **Query Parameters**: `status` (`DRAFT`, `ISSUED`, `PAID`, `CANCELLED`), `customer_id`, `opportunity_id`.
- **Response**: `200 OK` with line items, tax breakdown, and payment status.

### `POST /api/v1/invoices`
Generates an official tax invoice.

- **Payload**:
```json
{
  "customer_id": "cust-94",
  "opportunity_id": "opp-31",
  "service_type": "BROKERAGE_COMMISSION",
  "base_amount": 62500.00,
  "tax_rate": 0.15,
  "tax_amount": 9375.00,
  "total_amount": 71875.00
}
```
- **Response**: `201 Created` with generated `invoice_id`.

### `POST /api/v1/invoices/{invoice_id}/payments`
Records a customer payment receipt.

- **Payload**:
```json
{
  "amount": 71875.00,
  "payment_method": "SADAD",
  "reference_number": "SADAD-9482718",
  "payment_date": "2026-10-31"
}
```
- **Response**: `200 OK` updating invoice status to `PAID`.

---

## 7. Tasks, Workflow & SOPs (`/api/v1/tasks`)

### `GET /api/v1/tasks`
Lists tasks assigned to the caller or their team.

- **Query Parameters**:
  - `status`: `OPEN`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`
  - `priority`: `LOW`, `NORMAL`, `HIGH`, `URGENT`
  - `assigned_user_id`: Filter by user
- **Response**: `200 OK` with tasks including due dates, SLA warnings, and template references.

### `GET /api/v1/tasks/{task_id}`
Returns task details alongside the complete SOP checklist guidance.

- **Response**: `200 OK` with step-by-step checklist items and mandatory verification flags.

### `PUT /api/v1/tasks/{task_id}/complete`
Marks a task complete after validating SOP items.

- **Payload**:
```json
{
  "checklist_responses": {
    "verified_title_deed": true,
    "confirmed_buyer_identity": true,
    "signed_representation_agreement": true
  },
  "completion_notes": "All checks validated and approved."
}
```
- **Response**: `200 OK` triggering automatic downstream tasks.

### `POST /api/v1/tasks/{task_id}/reopen`
Smart reopen capability for completed tasks.

- **Payload**:
```json
{
  "reopen_reason": "Client amended search criteria to require 4 bedrooms instead of 3.",
  "requested_by": "user-52"
}
```
- **Response**: `200 OK` restoring task status to `OPEN` and adjusting opportunity status accordingly.

---

## 8. Real Estate Financial Calculations (`/api/v1/calculations`)

### `POST /api/v1/calculations/brokerage-fee`
Calculates statutory brokerage fee and ZATCA VAT according to REGA limits.

- **Payload**:
```json
{
  "deal_value": 2500000.00,
  "fee_percentage": 2.5
}
```
- **Response**: `200 OK`
```json
{
  "data": {
    "deal_value": 2500000.00,
    "fee_percentage": 2.5,
    "brokerage_fee": 62500.00,
    "vat_rate": 0.15,
    "vat_amount": 9375.00,
    "total_invoice_amount": 71875.00
  }
}
```

### `POST /api/v1/calculations/investment-returns`
Calculates commercial investment metrics.

- **Payload**:
```json
{
  "purchase_price": 10000000.00,
  "annual_gross_rent": 950000.00,
  "operating_expenses": 120000.00
}
```
- **Response**: `200 OK`
```json
{
  "data": {
    "purchase_price": 10000000.00,
    "annual_gross_rent": 950000.00,
    "operating_expenses": 120000.00,
    "net_operating_income": 830000.00,
    "gross_yield_percentage": 9.50,
    "cap_rate_percentage": 8.30
  }
}
```

---

## 9. System Administration & RBAC (`/api/v1/admin`)

### `GET /api/v1/admin/users`
Returns all registered system users with their active roles, branches, and status.

### `GET /api/v1/admin/audit-logs`
Returns the immutable system audit trail.

- **Query Parameters**:
  - `entity_type`: `LEAD`, `OPPORTUNITY`, `INVOICE`, `TASK`, `UNIT`
  - `user_id`: Filter by acting user
  - `from_date` / `to_date`: ISO timestamps
- **Response**: `200 OK` with paginated audit logs.

---

## 10. Managerial KPIs, Operational Calendar & Financial Schedules (`/api/v1/reports`)

### `GET /api/v1/reports/agenda-calendar`
Retrieves consolidated operational events across unfinished and unexecuted tasks, site viewings, unit reservations, periodic rent collections, and work orders that have scheduled dates and deadlines (`uncompleted_only=true` by default). Supports both interactive calendar and agenda timeline views with explicit entity keys (`lead_id`, `task_id`, `viewing_id`, `reservation_id`).

- **Query Parameters**:
  - `scope` (optional): `GLOBAL`, `BRANCH`, `TEAM`, `OWN` (defaults to user's assigned scope).
  - `branch_id` (optional): Filter by specific branch.
  - `user_id` (optional): Filter by specific agent.
  - `lead_id` (optional): Filter events scoped to a specific Lead ID.
  - `opportunity_id` (optional): Filter events scoped to a specific Opportunity ID.
  - `event_type` (optional): `ALL`, `TASK`, `VIEWING`, `RESERVATION`, `RENT_COLLECTION`, `WORK_ORDER`, `CAMPAIGN`.
  - `uncompleted_only` (optional, default `true`): When true, strictly excludes completed (`COMPLETED`), cancelled (`CANCELLED`), converted (`CONVERTED`), or paid (`PAID`) records, returning only unexecuted items with deadlines. Set to `false` to include historical completed records.
  - `start_date` / `end_date` (optional): ISO date range (`YYYY-MM-DD`).
- **Headers**:
  - `X-User-ID: user-51`
- **Response**: `200 OK`
```json
{
  "data": {
    "summary": {
      "total_events": 236,
      "tasks_count": 180,
      "viewings_count": 28,
      "reservations_count": 12,
      "rent_collections_count": 10,
      "work_orders_count": 6,
      "today_count": 4,
      "overdue_count": 15
    },
    "scope_info": {
      "scope": "GLOBAL",
      "branch_id": null,
      "branch_name": null,
      "user_id": null,
      "user_name": null
    },
    "events": [
      {
        "event_id": "task-102",
        "event_type": "TASK",
        "event_type_label_ar": "مهمة تشغيلية",
        "event_type_label_en": "Task",
        "title": "متابعة توثيق عقد إيجار",
        "event_date": "2026-10-25",
        "end_date": null,
        "lead_id": "lead-102",
        "task_id": "task-102",
        "viewing_id": null,
        "reservation_id": null,
        "opportunity_id": "opp-88",
        "unit_id": "unit-10",
        "unit_number": "A-102",
        "customer_name": "سلطان الشمري",
        "assigned_user_id": "user-27",
        "assigned_user_name": "شهد العتيبي",
        "branch_name": "فرع مكة المكرمة",
        "priority": "HIGH",
        "status": "PENDING",
        "status_label_ar": "قيد الانتظار",
        "badge_color": "#f59e0b",
        "amount": null
      }
    ]
  },
  "meta": {
    "request_id": "7820ebdf-4a6c-4869-9069-7ad3004bb15b"
  }
}
```

### `GET /api/v1/reports/financial-schedule`
Retrieves an itemized schedule of financial dues and receivables, categorized into Deals & Leads (`DEALS_LEADS` - invoices and reservation Araboun), Property Management (`PROPERTY_MANAGEMENT` - rent collections and maintenance work orders), and Marketing (`MARKETING` - campaign budgets). Includes collection status indicators, overdue day calculations, and summary collection rate KPIs.

- **Query Parameters**:
  - `scope` (optional): `GLOBAL`, `BRANCH`, `TEAM`, `OWN`.
  - `branch_id` (optional): Filter by branch.
  - `user_id` (optional): Filter by user.
  - `lead_id` (optional): Filter financial records scoped to a specific Lead ID.
  - `opportunity_id` (optional): Filter financial records scoped to a specific Opportunity ID.
  - `category` (optional): `ALL`, `DEALS_LEADS`, `PROPERTY_MANAGEMENT`, `MARKETING`.
  - `collection_status` (optional): `ALL`, `COLLECTED`, `PENDING`, `OVERDUE`, `CANCELLED`.
- **Headers**:
  - `X-User-ID: user-51`
- **Response**: `200 OK`
```json
{
  "data": {
    "summary": {
      "total_dues_amount": 714081.25,
      "total_collected_amount": 405456.25,
      "total_pending_amount": 268625.00,
      "total_overdue_amount": 40000.00,
      "collection_rate_percent": 56.78,
      "deals_leads_count": 20,
      "property_management_count": 10,
      "marketing_count": 2,
      "total_items": 32
    },
    "scope_info": {
      "scope": "GLOBAL",
      "branch_id": null,
      "branch_name": null,
      "user_id": null,
      "user_name": null
    },
    "items": [
      {
        "item_id": "inv-001",
        "category": "DEALS_LEADS",
        "category_label_ar": "الصفقات والطلبات",
        "item_type_code": "TAX_INVOICE",
        "item_type_label_ar": "فاتورة سعي وساطة ضريبية",
        "item_type_label_en": "Tax Invoice",
        "title": "فاتورة سعي صفقة #opp-55",
        "lead_id": "lead-62",
        "opportunity_id": "opp-55",
        "unit_id": "unit-01",
        "unit_number": "V-01",
        "customer_name": "عبدالله الراجحي",
        "amount": 57500.00,
        "amount_paid": 57500.00,
        "amount_remaining": 0.00,
        "collection_status": "COLLECTED",
        "collection_status_ar": "تم التحصيل",
        "badge_color": "#10b981",
        "due_date": "2026-10-30",
        "collected_at": "2026-10-29T14:00:00Z",
        "assigned_user_name": "إبراهيم النمري",
        "branch_name": "فرع الرياض",
        "days_overdue": 0
      }
    ]
  },
  "meta": {
    "request_id": "b1e7c082-f5c7-43a1-a67b-fba010a34b22"
  }
}
```

---

## 11. Internal Task Reminders & Contextual Messaging API (المراسلات والتذكيرات الداخلية)

### 11.1. Create Task Reminder Ping
* **Method**: `POST`
* **Path**: `/api/v1/internal-pings`
* **Headers**: `X-User-ID: <user_id>`
* **Description**: Sends a non-destructive contextual reminder ping linked to an operational task, viewing, rent installment, invoice, or work order, carrying a row snapshot without mutating task or financial state.
* **Request Body**:
```json
{
  "recipient_role": "DIRECT_MANAGER",
  "recipient_user_id": "user-5",
  "context_type": "TASK",
  "context_id": "TSK-102",
  "context_snapshot": {
    "rowId": "TSK-102",
    "title": "الاتصال الأولي بالعميل ومطابقة المتطلبات",
    "customer": "سلطان بن عبدالعزيز",
    "amount": "1,250,000 SAR",
    "assignedUser": "سلطان الغامدي"
  },
  "message_text": "تذكير: نرجو استكمال الاتصال بالعميل وتوثيق رغباته قبل انتهاء مهلة الـ 30 دقيقة المعتمدة.",
  "urgency_level": "URGENT",
  "is_archived": false
}
```
* **Response `201 Created`**:
```json
{
  "data": {
    "ping_id": "PNG-20261102-A1B2C3",
    "sender_user_id": "user-51",
    "sender_name": "معاذ النمري",
    "recipient_role": "DIRECT_MANAGER",
    "recipient_user_id": "user-5",
    "recipient_name": "نواف الزهراني",
    "context_type": "TASK",
    "context_id": "TSK-102",
    "context_snapshot": { ... },
    "message_text": "تذكير: نرجو استكمال الاتصال بالعميل...",
    "urgency_level": "URGENT",
    "is_read": false,
    "read_at": null,
    "is_archived": false,
    "archived_at": null,
    "created_at": "2026-11-02T00:30:00Z"
  }
}
```

### 11.2. Get Pings Inbox
* **Method**: `GET`
* **Path**: `/api/v1/internal-pings/inbox?filter_type=ALL&limit=50`
* **Headers**: `X-User-ID: <user_id>`
* **Parameters**: `filter_type` (`ALL`, `UNREAD`, `ARCHIVED`, `SENT`), `limit` (default: 50).
* **Response `200 OK`**:
```json
{
  "data": {
    "pings": [ ... ],
    "summary": {
      "total_count": 12,
      "unread_count": 2,
      "archived_count": 4
    }
  }
}
```

### 11.3. Toggle Read Status
* **Method**: `PATCH`
* **Path**: `/api/v1/internal-pings/{ping_id}/read`
* **Response `200 OK`**: Returns updated ping with toggled `is_read` and timestamped `read_at`.

### 11.4. Toggle Archive as Proof
* **Method**: `PATCH`
* **Path**: `/api/v1/internal-pings/{ping_id}/archive`
* **Description**: Toggles `is_archived` status, pinning the message as immutable sender/recipient diligence evidence protected from automated 90-day purging.
* **Response `200 OK`**: Returns updated ping with toggled `is_archived` and timestamped `archived_at`.

### 11.5. Clean Up Expired Transient Pings (Retention Policy)
* **Method**: `POST`
* **Path**: `/api/v1/internal-pings/cleanup-expired?retention_days=90`
* **Description**: Automatically purges read, non-archived transient pings older than `retention_days`, while strictly preserving all archived proofs.
* **Response `200 OK`**:
```json
{
  "data": {
    "purged_count": 14,
    "retained_proofs_count": 28,
    "message": "Cleaned up 14 transient pings older than 90 days. 28 documented proofs retained indefinitely."
  }
}
```

### 11.6. Get Row Pings Thread
* **Method**: `GET`
* **Path**: `/api/v1/internal-pings/row-thread?context_type=TASK&context_id=TSK-102`
* **Response `200 OK`**: Returns chronological array of all reminder pings exchanged for this specific operational record.



