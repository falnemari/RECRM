# Authentication & Authorization Guide

> **Audience**: Full-stack developers, security engineers, and DevOps administrators.  
> **Scope**: Session authentication mechanism, Role-Based Access Control (RBAC), multi-tier data scoping (`GLOBAL`, `BRANCH`, `TEAM`, `OWN`), SQL-level query isolation, and the developer user switcher.

---

## 1. Authentication Architecture

In the current development and internal network deployment, RECRM uses a **Header-Based Authentication Mechanism** driven by the `X-User-ID` HTTP header.

```
+-----------------------------------------------------------------------------------+
|                                Client Application                                 |
|                                                                                   |
|  1. Active user ID stored in localStorage: 'recrm_user_id' = 'user-51'            |
|  2. Attached to all fetch requests: headers['X-User-ID'] = 'user-51'              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  HTTP GET /api/v1/leads
                                         |  Header: X-User-ID: user-51
+-----------------------------------------------------------------------------------+
|                              FastAPI Backend Router                               |
|                                                                                   |
|  3. Router receives x_user_id: Optional[str] = Header("user-51")                  |
|  4. Calls resolve_data_scope_filter(conn, x_user_id, requested_assigned_user_id)  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        PostgreSQL Dynamic Query Scoping                           |
|                                                                                   |
|  5. Resolves User Roles & Scope Type (GLOBAL, BRANCH, TEAM, OWN)                  |
|  6. Appends WHERE clause:                                                         |
|     - GLOBAL: Unrestricted (sees all 5 branches)                                  |
|     - BRANCH: WHERE branch_id = $1                                                |
|     - OWN:    WHERE assigned_user_id = $1                                         |
+-----------------------------------------------------------------------------------+
```

### Why Header Authentication for Development?
- **Zero Login Friction**: Team members, testers, and automated integration test suites can instantly switch between roles (Admin, Agent, Manager, Accountant) without managing JWT expiration tokens or OAuth redirect flows.
- **Microservice Ready**: Downstream internal services behind an API Gateway can trust the validated user ID passed via gateway headers.

### Production Migration Roadmap
In production internet deployments, this mechanism should be wrapped with an **OAuth 2.0 / OpenID Connect (OIDC)** provider (e.g. Auth0, Keycloak, or Saudi National Single Sign-On / Nafath):
1. Client authenticates and receives a cryptographically signed JWT.
2. FastAPI `Depends(OAuth2PasswordBearer)` decodes and validates the JWT signature.
3. The verified `sub` claim is mapped to the internal `user_id`.

---

## 2. Role-Based Access Control (RBAC)

The RECRM security model is defined across three database tables:
1. `roles`: Catalog of 10 defined operational roles.
2. `permissions`: Atomic action rights (`LEAD_READ`, `SALES_WRITE`, `PAYMENT_APPROVE`, `ADMIN`).
3. `user_roles`: Junction table assigning one or more roles to each user.

### The 10 System Roles:
| Role Code | Arabic Name | English Name | Functional Authority |
|---|---|---|---|
| `SYS_ADMIN` | مسؤول النظام | System Administrator | Unrestricted superuser access to all data, settings, user accounts, and system configuration. |
| `SALES_DIRECTOR` | المدير التنفيذي للمبيعات | Sales Director | Oversees company-wide sales strategy, team pipelines, and high-value deal approvals. |
| `SALES_MANAGER` | مدير المبيعات | Sales Manager | Supervises branch brokers, reassigns leads, reviews deal negotiations, approves viewing schedules. |
| `BRANCH_MANAGER` | مدير الفرع | Branch Manager | Oversees branch P&L, operational tasks, agent attendance, and branch commission splits. |
| `SALES_AGENT` | الوسيط العقاري المكلف | Sales Agent | Manages assigned buyers/investors, conducts property viewings, negotiates purchase offers. |
| `LEASING_AGENT` | وسيط التأجير | Leasing Agent | Handles rental inquiries, tenant screening, lease contract execution, and key handovers. |
| `PROPERTY_MANAGER` | مدير إدارة الأملاك | Property Manager | Administers landlord properties, building maintenance, occupancy rates, and facility contracts. |
| `ACCOUNTANT` | قسم المالية والمحاسبة | Finance & Accounting | Issues ZATCA tax invoices, records customer payments, calculates commissions, executes owner payouts. |
| `DOCUMENT_CONTROL` | الإدارة القانونية وضابط العقود | Legal & Contract Control | Audits title deeds, validates buyer/seller AML risk, confirms contract compliance before closing. |
| `AUDITOR` | المدقق والمراجع | Auditor / Compliance | Read-only compliance oversight across all records, transactions, audit logs, and tax ledgers. |
| `VIEWER` | مشاهد | Read-Only Viewer | Read-only view for trainees, external board members, or executive observers. |

---

## 3. The 4 Data Scoping Levels

Data visibility in RECRM is not simply binary (allowed vs denied); it is governed by **Data Scoping**:

```
+--------------------------------------------------------------------------------+
|                             DATA SCOPING HIERARCHY                             |
|                                                                                |
|    +----------------------------------------------------------------------+    |
|    | GLOBAL: SYS_ADMIN, GENERAL_MANAGER, AUDITOR, ACCOUNTANT, MARKETING   |    |
|    | (Sees all 5 branches: Riyadh, Jeddah, Al-Khobar, Makkah, Madinah)    |    |
|    +----------------------------------------------------------------------+    |
|                                       |                                        |
|    +----------------------------------------------------------------------+    |
|    | BRANCH: SALES_MANAGER, BRANCH_MANAGER, PROPERTY_MANAGER              |    |
|    | (Sees only records belonging to their assigned physical branch)      |    |
|    +----------------------------------------------------------------------+    |
|                                       |                                        |
|    +----------------------------------------------------------------------+    |
|    | TEAM: SALES_DIRECTOR                                                 |    |
|    | (Sees records across their supervised operational division)          |    |
|    +----------------------------------------------------------------------+    |
|                                       |                                        |
|    +----------------------------------------------------------------------+    |
|    | OWN: SALES_AGENT, LEASING_AGENT                                      |    |
|    | (Sees only leads, deals, and tasks assigned to their user_id)        |    |
|    +----------------------------------------------------------------------+    |
+--------------------------------------------------------------------------------+
```

### Implementation: `resolve_user_data_scope()`
Located in [`src/backend/app/routers/auth.py`](file:///home/nemro/RECRM/src/backend/app/routers/auth.py):

```python
def resolve_user_data_scope(role_codes: List[str]) -> str:
    codes = set(r.upper() for r in role_codes)
    # 1. Executive and organization-wide governance roles have global visibility
    if any(r in codes for r in ("SYS_ADMIN", "ADMIN", "GENERAL_MANAGER", "AUDITOR", "VIEWER")):
        return "GLOBAL"
    # 2. Branch sales managers oversee their branch pipeline
    if any(r in codes for r in ("SALES_MANAGER", "BRANCH_MANAGER")):
        return "BRANCH"
    # 3. Organization-wide functional specialists (Marketing & Central Finance)
    if any(r in codes for r in ("MARKETING", "ACCOUNTANT")):
        return "GLOBAL"
    # 4. Regional / Team directors
    if "SALES_DIRECTOR" in codes:
        return "TEAM"
    # 5. Branch operations (Property Managers & Document Controllers)
    if any(r in codes for r in ("PROPERTY_MANAGER", "DOCUMENT_CONTROL")):
        return "BRANCH"
    # 6. Frontline individual agents (isolated to their own records)
    if any(r in codes for r in ("SALES_AGENT", "LEASING_AGENT")):
        return "OWN"
    return "GLOBAL"
```

---

## 4. Query-Level SQL Enforcement

Data isolation is guaranteed at the database query layer. Endpoints call `resolve_data_scope_filter()` to determine exact SQL filtering clauses:

```python
# In src/backend/app/routers/leads.py
scope_info = await resolve_data_scope_filter(conn, x_user_id, assigned_user_id)

where_clauses = ["l.organization_id = $1"]
params = [scope_info["organization_id"]]

if scope_info["scope_type"] == "OWN":
    params.append(scope_info["user_id"])
    where_clauses.append(f"l.assigned_user_id = ${len(params)}")
elif scope_info["scope_type"] == "BRANCH":
    params.append(scope_info["branch_id"])
    where_clauses.append(f"l.branch_id = ${len(params)}")
# If GLOBAL, no user or branch restriction is added!
```

> [!IMPORTANT]
> Because filtering occurs inside the SQL `WHERE` clause, frontline agents cannot access deals or customer contact numbers belonging to another broker, even if they guess the database record ID.

---

## 5. Client-Side Authorization & Developer Switcher

Located in [`src/ui/user_session.js`](file:///home/nemro/RECRM/src/ui/user_session.js):

### 5.1. Page Access Verification (`PAGE_ACCESS_MAP`)
When any HTML page loads, `user_session.js` validates that the user's role has permission to access the view:

```javascript
const PAGE_ACCESS_MAP = {
    'invoices.html': {
        roles: ['SYS_ADMIN', 'ACCOUNTANT', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'AUDITOR']
    },
    'opportunities.html': {
        roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'BRANCH_MANAGER']
    }
};
```
If an unauthorized role visits the page, a full-screen access denied banner is rendered.

### 5.2. The User Switcher Modal
Developers and testers can click the user avatar in the top navigation bar to open the switch modal. Selecting another user executes:

```javascript
window.switchActiveUser = function(targetUid) {
    localStorage.setItem('recrm_user_id', targetUid);
    
    // Broadcast change across all open browser tabs
    if (sessionChannel) {
        sessionChannel.postMessage({ type: 'USER_SWITCHED', userId: targetUid });
    }
    
    // Reload page immediately to reflect new scoping
    window.location.reload();
};
```

---

## 6. Seeded Personas for Testing Scopes

Use these seeded user accounts to test different roles and permission scopes:

| User ID | Name | Role | Branch | Test Scenario |
|---|---|---|---|---|
| `user-51` | Fahad Kh. Alnemari | `SYS_ADMIN` | Makkah (branch-3) | Full unrestricted access to all 5 branches, settings, and audit logs. |
| `user-1` | Tariq Al-Otaibi | `SALES_MANAGER` | Makkah (branch-3) | Supervises all Makkah leads, viewings, and brokers. Cannot see Riyadh deals. |
| `user-27` | Shahad Alnemari | `SALES_AGENT` | Madinah (branch-4) | Sees only leads and tasks assigned directly to `user-27`. |
| `user-19` | Demo Agent 26 | `ACCOUNTANT` | Makkah (branch-3) | Access to finance portal, invoices, payment receipts, and commission approvals. |
| `user-4` | Demo Agent 12 | `PROPERTY_MANAGER` | Al-Khobar (branch-5) | Manages leases, maintenance work orders, and landlord contracts. |
| `user-47` | Demo Agent 06 | `AUDITOR` | Makkah (branch-3) | Read-only access to all reports, audit logs, and compliance records across all branches. |

