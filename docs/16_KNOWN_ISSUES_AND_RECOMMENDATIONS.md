# Known Issues & Strategic Recommendations

> **Audience**: Product owners, engineering managers, software architects, and core developers.  
> **Scope**: Prioritized technical debt inventory, operational edge cases, Saudi regulatory integration roadmap, and actionable recommendations organized across 10 strategic domains.

---

## 1. Executive Summary & Prioritization Matrix

This document provides a forward-looking engineering roadmap for RECRM. While the current implementation delivers a complete, verified core for Saudi real estate brokerage workflows, transitioning to an enterprise-grade, multi-branch production deployment requires addressing key technical debt and platform enhancements.

```
+-----------------------------------------------------------------------------------------+
|                               RECOMMENDATION PRIORITY MATRIX                            |
|                                                                                         |
|   IMMEDIATE (Sprint 1-2)       | NEAR-TERM (Sprint 3-4)       | STRATEGIC (Future)      |
|   - Restrict CORS policy       | - JWT / OAuth2 Auth          | - Real ZATCA Phase 2    |
|   - Add composite DB indexes   | - Decompose WorkflowEngine   | - Real REGA / FAL API   |
|   - Sanitize doc HTML templates| - WebSocket live push alerts | - Ejar API Integration  |
|   - Dedup modal markup in JS   | - Redis caching for catalogs | - Nafath ID integration |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Detailed Focus Areas

### 2.1. Security Hardening
- **Current State**: Internal intranet header authentication (`X-User-ID: user-51`), wildcard CORS (`*`).
- **Issue**: Unauthorized users on the local network or third-party web pages could spoof identities or make unauthorized requests.
- **Recommendation**:
  1. Restrict CORS origins in [`main.py`](file:///home/nemro/RECRM/src/backend/app/main.py) to explicit trusted domains (`https://crm.agency.sa`).
  2. Implement OAuth2 with JWT tokens stored in `HttpOnly` cookies.
  3. Adopt Jinja2 with `autoescape=True` in [`document_templates.py`](file:///home/nemro/RECRM/src/backend/app/services/document_templates.py) to prevent HTML injection in contract previews.

### 2.2. Database & Data Integrity
- **Current State**: 53 normalized tables, 45 sequences, strong foreign keys.
- **Issue**: High-growth transactional tables (`lead_events`, `tasks`, `audit_logs`) lack composite indexes for compound queries used by dashboards.
- **Recommendation**:
  1. Add composite indexes on `(assigned_user_id, status)` and `(lead_id, created_at DESC)`.
  2. Implement automated daily database backup scripts (`pg_dump` with S3/remote storage replication).

### 2.3. Architecture & Modularity
- **Current State**: Single monolithic `WorkflowEngine` class (~8,680 lines).
- **Issue**: High cognitive complexity and high merge conflict risk during team development.
- **Recommendation**:
  1. Decompose `WorkflowEngine` into 5 focused sub-services (`lead_workflow`, `reservation_service`, `sop_service`, `cancellation_service`, `reopen_service`).
  2. Standardize data scoping into a reusable dependency (`Depends(get_data_scope)`).

### 2.4. Missing Saudi Regulatory Integrations (Roadmap)
- **Current State**: Real estate mathematics, fee limits, and tax formulas are fully implemented, but external government APIs are simulated locally.
- **Recommendations for External Integration**:
  1. **ZATCA Phase 2 Integration**: Implement cryptographic signing (ECDSA with secp256k1), UBL 2.1 XML generation, and ZATCA compliance API clearance.
  2. **REGA / FAL Real Estate Authority**: Direct integration with the Real Estate General Authority API to validate broker license numbers (`رخصة فال`) and fetch authenticated title deed data.
  3. **Ejar Platform**: Automate electronic lease contract registration and status synchronization directly with Ejar API.
  4. **Nafath (National Single Sign-On)**: Enable two-factor biometric verification for buyers and sellers signing legal contracts.

### 2.5. Concurrency & Performance
- **Current State**: `SELECT ... FOR UPDATE` locks prevent double-booking. Connection pool size is fixed (min: 2, max: 20).
- **Issue**: Peak booking campaigns (e.g. launching a 200-unit project) could cause lock contention or pool exhaustion.
- **Recommendation**:
  1. Implement an exponential backoff deadlock retry decorator on transaction blocks.
  2. Introduce Redis for caching static catalogs (`cities`, `districts`, `property_types`) to reduce database query load by 35%.

### 2.6. User Experience & Responsive Design
- **Current State**: Responsive layout works well on desktop (1920x1080) and laptop screens (1366x768).
- **Issue**: On mobile phones (375px–430px), high-density data tables require horizontal scrolling.
- **Recommendation**:
  1. Implement adaptive card views for tables on screens smaller than 768px.
  2. Introduce browser push notifications or WebSockets so brokers receive immediate alerts when a lead is assigned or an earnest deposit is paid.

### 2.7. Frontend Code Maintainability
- **Current State**: Vanilla JS and native HTML across 12 portal files.
- **Issue**: Modal HTML markup is duplicated across multiple HTML files.
- **Recommendation**:
  1. Centralize reusable dialog generation into `common.js` using a clean factory pattern: `RECRM.modal.open({...})`.
  2. Extract common CSS variables into a shared stylesheet (`styles/theme.css`) instead of per-page `<style>` blocks.

### 2.8. Automated Testing & Quality Assurance
- **Current State**: 31 test files, 198 automated integration tests covering backend routes and workflows.
- **Issue**: Frontend DOM interactions, modal toggling, and table rendering are tested manually.
- **Recommendation**:
  1. Introduce headless browser end-to-end tests using Playwright or Cypress to automate UI validation across all 12 portals.
  2. Add automated load tests (using Locust or k6) simulating 100 concurrent brokers reserving units.

### 2.9. Operational Edge Cases & Error Handling
- **Issue 1: Agent Resignation / Inactivity**: If an agent is deactivated, open leads and pending tasks remain assigned to them until manually reassigned.
  - *Fix*: Create a bulk lead reassignment wizard for Sales Managers in `system_settings.html`.
- **Issue 2: 48h Reservation Expiry Worker in Multi-Node Clusters**:
  - *Current State*: The background worker runs as an `asyncio.create_task` inside the single backend process.
  - *Fix*: If scaling to multiple Uvicorn worker processes or containers, use a distributed task scheduler (such as Celery or ARQ with Redis, or PostgreSQL advisory locks) to prevent redundant expiry sweeps.

### 2.10. Documentation & Knowledge Transfer
- **Recommendation**:
  1. Maintain this 17-document architecture library as part of every code review.
  2. Create video walkthroughs or visual SOP tutorials for onboarding junior real estate brokers.

