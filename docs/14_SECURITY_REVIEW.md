# Security Review & Vulnerability Assessment

> **Audience**: Security officers, full-stack engineers, and compliance auditors.  
> **Scope**: Security architecture assessment, vulnerability inventory (SEC-01 through SEC-06), risk ratings, remediation roadmaps, and compliance with Saudi data regulations (PDPL).

---

## 1. Executive Summary

A comprehensive architectural and code-level security assessment was conducted across the RECRM platform (FastAPI backend, PostgreSQL database, and Vanilla JavaScript frontend). 

The platform demonstrates **strong defensive engineering** in database safety (complete elimination of SQL injection via parameterized queries, strict transaction isolation, and row-level locking concurrency controls). However, because the system was initially engineered for rapid local intranet development, its authentication, CORS, and template rendering mechanisms require hardening before exposure to public internet traffic.

### Threat Landscape Summary:
```
+-----------------------------------------------------------------------------------------+
|                                    RISK SUMMARY MATRIX                                  |
|                                                                                         |
|   CRITICAL: 0       HIGH: 1       MEDIUM: 3       LOW: 2       INFORMATIONAL: 1         |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Vulnerability Inventory & Findings

### Finding SEC-01: Header-Based Authentication Spoofing
- **Severity**: **HIGH**
- **Impact Area**: Authentication & Authorization (`src/backend/app/routers/auth.py`)
- **CVSS 3.1 Base Score**: 8.1 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N`)
- **Observed Behavior**:  
  The API trusts the client-supplied HTTP header `X-User-ID: <user_id>` without verifying cryptographic signatures, passwords, or session tokens. Any user or script that sets `X-User-ID: user-51` immediately acquires superadmin (`SYS_ADMIN`) permissions.
- **Proof of Concept**:
  ```bash
  # Any unauthorized client can impersonate the system administrator
  curl -H "X-User-ID: user-51" http://localhost:8000/api/v1/auth/me
  ```
- **Remediation Plan**:
  1. Transition from raw header authentication to JSON Web Tokens (JWT) using `fastapi.security.OAuth2PasswordBearer`.
  2. Implement an authenticated login endpoint (`POST /api/v1/auth/login`) that validates passwords hashed with `bcrypt` or `argon2id`.
  3. Store JWTs in `HttpOnly`, `SameSite=Strict`, `Secure` cookies to prevent client-side script theft.

---

### Finding SEC-02: Permissive Wildcard CORS Configuration
- **Severity**: **MEDIUM**
- **Impact Area**: HTTP Gateway & Middleware (`src/backend/app/main.py#L63-L70`)
- **CVSS 3.1 Base Score**: 6.5 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N`)
- **Observed Behavior**:  
  The backend permits requests from all origins with credential sharing enabled:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Impact**: Malicious third-party websites visited by an authenticated broker could theoretically execute unauthorized API requests against the local CRM if exposed without network isolation.
- **Remediation Plan**:
  Replace `allow_origins=["*"]` with an explicit whitelist loaded from environment configuration:
  ```python
  allowed_origins = settings.ALLOWED_ORIGINS.split(",")  # e.g. ["https://crm.agency.sa"]
  app.add_middleware(
      CORSMiddleware,
      allow_origins=allowed_origins,
      allow_credentials=True,
      allow_methods=["GET", "POST", "PUT", "DELETE"],
      allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
  )
  ```

---

### Finding SEC-03: Lack of Rate Limiting & DoS Protection
- **Severity**: **MEDIUM**
- **Impact Area**: API Gateway & Public Routes
- **CVSS 3.1 Base Score**: 5.3 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L`)
- **Observed Behavior**:  
  The application lacks rate limiting. Automated scrapers or brute-force scripts could flood endpoints like `POST /api/v1/leads` or `POST /api/v1/properties/match-units`, exhausting database connection pools and degrading performance.
- **Remediation Plan**:
  Introduce `slowapi` or an Nginx/Cloudflare reverse proxy rate limiter configured to 100 requests per minute per IP address.

---

### Finding SEC-04: HTML Injection Risk in Raw Document Templates
- **Severity**: **MEDIUM**
- **Impact Area**: Document Generation (`src/backend/app/services/document_templates.py`)
- **CVSS 3.1 Base Score**: 6.1 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N`)
- **Observed Behavior**:  
  Document templates concatenate user input strings (such as customer names or property descriptions) directly into HTML markup strings using Python formatted strings. If a customer name contains `<script>alert(1)</script>`, the code executes inside the browser of any staff member viewing the generated contract.
- **Remediation Plan**:
  1. Migrate document rendering to **Jinja2** with automatic HTML escaping enabled (`autoescape=True`).
  2. Sanitize all customer free-text inputs using Python's `bleach` or `html.escape()` before injecting into documents.

---

### Finding SEC-05: Plaintext Credentials in Local `.env`
- **Severity**: **LOW**
- **Impact Area**: Configuration & Secret Management
- **Observed Behavior**:  
  PostgreSQL database passwords and administrative settings are stored in plaintext `.env` files on the development filesystem.
- **Remediation Plan**:
  - Ensure `.env` is permanently included in `.gitignore` (already verified).
  - In staging/production environments, inject secrets via environment variables or secret management vaults (e.g. Docker Secrets, AWS Secrets Manager, or HashiCorp Vault).

---

### Finding SEC-06: PII Read-Access Audit Logging Gaps
- **Severity**: **LOW**
- **Impact Area**: Compliance & Data Governance (`src/backend/app/routers/leads.py`, `customers.py`)
- **Observed Behavior**:  
  Under the Saudi **Personal Data Protection Law (PDPL / نظام حماية البيانات الشخصية)**, access to sensitive Personally Identifiable Information (National ID, phone numbers, financial records) must be auditable. RECRM currently logs all state changes (mutations) in `audit_logs` and document views in `document_access_log`, but does not record read access on bulk customer queries.
- **Remediation Plan**:
  Add an audit log trigger on `GET /api/v1/customers/{customer_id}` and bulk lead exports recording the timestamp and accessing `user_id`.

---

## 3. Security Architecture Strengths

Despite the development-mode findings above, RECRM includes several architectural safeguards:

1. **Complete Immunity to SQL Injection**:  
   All SQL statements across all 16 routers and services use **pure parameterized queries** with `$1, $2, ...` placeholders via `asyncpg`. No dynamic string concatenation is used in SQL statements.
2. **Strict Concurrency Protection**:  
   Critical operations (unit reservations, financial ledger mutations) utilize `SELECT ... FOR UPDATE` row-level exclusive locks inside database transactions, preventing race conditions and double-spending.
3. **Hardened HTTP Response Headers**:  
   Injected via custom middleware in [`main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L76-L84):
   - `X-Content-Type-Options: nosniff` (prevents MIME-type confusion attacks)
   - `X-Frame-Options: SAMEORIGIN` (prevents clickjacking attacks)
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `X-XSS-Protection: 1; mode=block`
4. **Data Isolation via SQL Scoping**:  
   Frontline agents cannot bypass data scoping filters by manipulating request parameters because the restriction is enforced directly in the database `WHERE` clause.

