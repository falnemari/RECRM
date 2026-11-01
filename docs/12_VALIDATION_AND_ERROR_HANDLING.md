# Validation & Error Handling Guide

> **Audience**: Backend and frontend developers, QA engineers, and system integrators.  
> **Scope**: The 4-layer validation architecture, Pydantic V2 schema enforcement, unified error envelopes, transactional rollbacks, and client-side error rendering.

---

## 1. The 4-Layer Validation Architecture

To ensure total data integrity, prevent invalid state transitions, and protect against corrupt financial ledgers, RECRM implements defense-in-depth across **four distinct layers**:

```
+-----------------------------------------------------------------------------------------+
|                               FOUR-LAYER VALIDATION MODEL                               |
|                                                                                         |
|   [ Layer 1: Client-Side (HTML5 & DOM) ]                                                |
|   - Regex patterns (Saudi Mobile: +966..., National ID: 10 digits)                     |
|   - Input constraints: required, min, max, type="number"                                |
|   - Immediate inline validation before network dispatch                                 |
|                                       |                                                 |
|                                       v HTTP Request                                    |
|   [ Layer 2: API Gateway & Schemas (Pydantic V2) ]                                      |
|   - Strict type coercion (strings, integers, floats, ISO datetimes)                     |
|   - Field-level validators (@field_validator)                                           |
|   - Multi-field cross-validation (@model_validator)                                     |
|   - Intercepted by FastAPI RequestValidationError -> Returns ErrorEnvelope (422)        |
|                                       |                                                 |
|                                       v Valid Schema                                    |
|   [ Layer 3: Service Domain & State Machine (WorkflowEngine) ]                          |
|   - Legal pipeline state transitions (DISCOVERY -> QUALIFIED -> WON)                    |
|   - SOP checklist completeness checks (mandatory document verification)                 |
|   - Gated cancellation prerequisites (all financial remedies completed)                 |
|   - Raises HTTPException(status_code=400, detail="...")                                 |
|                                       |                                                 |
|                                       v Valid Business Logic                            |
|   [ Layer 4: Database Storage (PostgreSQL Constraints & Locks) ]                        |
|   - Foreign Key integrity (ON DELETE RESTRICT)                                          |
|   - CHECK constraints (e.g. price > 0, fee_percentage <= 2.5)                           |
|   - NOT NULL constraints & UNIQUE indexes                                               |
|   - Row-level concurrency locking (SELECT ... FOR UPDATE)                               |
|   - Atomic transaction rollbacks (async with conn.transaction())                        |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Layer 2: Schema Validation & Error Transformation

FastAPI validates all incoming JSON request bodies against Pydantic models. If any field fails validation, FastAPI raises a `RequestValidationError`.

In RECRM, this is intercepted by a custom global exception handler in [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L86-L106):

```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    field_errors = {}
    
    # Restructure Pydantic error list into a clean dictionary
    for err in exc.errors():
        loc = ".".join(str(l) for l in err["loc"] if l != "body")
        msg = err["msg"]
        field_errors.setdefault(loc, []).append(msg)

    error_body = ErrorEnvelope(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="One or more fields are invalid.",
            request_id=req_id,
            fields=field_errors
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
        content=error_body.model_dump()
    )
```

### The Resulting JSON Error Envelope:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "request_id": "84c2a11b-3ef1-4b19-b5f7-6bc82df09e1a",
    "fields": {
      "budget_max": ["Input should be greater than budget_min."],
      "phone": ["Saudi mobile number must start with +966 or 05 and contain 9 subsequent digits."]
    }
  }
}
```

---

## 3. Standard System Error Taxonomy

| Error Code | HTTP Status | Root Cause | Example Scenario |
|---|---|---|---|
| `VALIDATION_ERROR` | `422 Unprocessable` | Schema constraint failed | Missing required `phone` or negative `price`. |
| `INVALID_STAGE_TRANSITION` | `400 Bad Request` | State machine rule violation | Attempting to move deal from `DISCOVERY` directly to `WON`. |
| `MISSING_SOP_CHECKLIST_ITEMS` | `400 Bad Request` | Required checklist items unchecked | Completing verification task without verifying title deed. |
| `CONCURRENCY_CONFLICT` | `409 Conflict` | Target resource locked or changed | Another broker completed reservation on the unit first. |
| `GATED_CANCELLATION_BLOCKED` | `400 Bad Request` | Unresolved remedies block cancel | Opportunity has active earnest deposit or open tax invoice. |
| `UNAUTHORIZED_ACCESS` | `403 Forbidden` | Access denied by RBAC or Scoping | Sales Agent attempting to read another broker's private lead. |
| `RESOURCE_NOT_FOUND` | `404 Not Found` | Primary key does not exist | Requesting `GET /leads/lead-99999`. |
| `DATABASE_ERROR` | `500 Internal Error` | PostgreSQL connection or query crash | Database server restart or unexpected constraint violation. |

---

## 4. Transactional Rollback Pattern

Financial and workflow operations spanning multiple tables must be atomic. If any sub-query fails, all previous writes within the transaction are rolled back automatically:

```python
async with conn.transaction():
    # 1. Deduct earnest money balance
    await conn.execute(
        "UPDATE reservations SET deposit_status = 'REFUNDED' WHERE reservation_id = $1", 
        reservation_id
    )
    
    # 2. Release unit back to AVAILABLE
    await conn.execute(
        "UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", 
        unit_id
    )
    
    # 3. Create credit memo invoice
    # If this query fails (e.g. invalid foreign key), steps 1 and 2 are NEVER committed!
    await conn.execute(
        "INSERT INTO invoices (invoice_id, ...) VALUES ($1, ...)",
        credit_invoice_id
    )
```

> [!TIP]
> Always use `async with conn.transaction():` when performing 2 or more related SQL operations. If an exception is raised inside the context block, `asyncpg` automatically issues a `ROLLBACK` to PostgreSQL.

---

## 5. Client-Side Error Presentation

Frontend portals handle errors centrally using `common.js`:

```javascript
try {
    const result = await apiRequest('/api/v1/sales/opportunities/opp-15/reserve', {
        method: 'POST',
        body: JSON.stringify(reservationPayload)
    });
    showToast('تم حجز الوحدة بنجاح', 'success');
} catch (error) {
    // Displays non-blocking, accessible red error toast to user
    showToast(`تعذر إتمام الحجز: ${error.message}`, 'error');
    
    // Highlight specific form inputs if field-level errors were returned
    if (error.fields) {
        Object.keys(error.fields).forEach(fieldName => {
            const input = document.querySelector(`[name="${fieldName}"]`);
            if (input) {
                input.classList.add('is-invalid');
                const helper = input.parentElement.querySelector('.invalid-feedback');
                if (helper) helper.textContent = error.fields[fieldName].join(', ');
            }
        });
    }
}
```

---

## 6. Beginner Developer Cheatsheet for Validation

### Recipe 1: Writing a Saudi Mobile Validator in Pydantic
```python
import re
from pydantic import BaseModel, field_validator

class LeadCreateIn(BaseModel):
    first_name: str
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_saudi_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-]", "", v)
        # Matches +9665XXXXXXXX or 05XXXXXXXX
        pattern = r"^(?:\+9665|05)\d{8}$"
        if not re.match(pattern, cleaned):
            raise ValueError(
                "رقم الجوال غير صالح. يجب أن يبدأ بـ +9665 أو 05 ويتكون من 10 أرقام."
            )
        return cleaned
```

### Recipe 2: Writing Cross-Field Comparison Validator
```python
from pydantic import BaseModel, model_validator

class PriceRangeCriteria(BaseModel):
    budget_min: float
    budget_max: float

    @model_validator(mode="after")
    def validate_budget_range(self):
        if self.budget_max < self.budget_min:
            raise ValueError("الحد الأقصى للميزانية يجب أن يكون أكبر من الحد الأدنى.")
        return self
```

### Recipe 3: Enforcing Business Rules in Service Layer
```python
if opportunity["stage"] == "WON":
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "DEAL_ALREADY_CLOSED",
            "message": "لا يمكن تعديل الشروط المالية لصفقة مكتملة ومغلقة بنجاح."
        }
    )
```

