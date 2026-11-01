# 04. Codebase & Project File Map
### الخريطة الشاملة لملفات ومكونات النظام

This document provides a comprehensive inventory and functional map of all source code files, configurations, scripts, and test suites across the **RECRM** repository.

---

## 1. Directory Tree Summary

```text
RECRM/
├── scripts/            # Database migration, schema inspection, and seed scripts
├── src/
│   ├── backend/        # FastAPI Application (Routers, Schemas, Services, Config)
│   │   ├── app/
│   │   │   ├── routers/    # 16 API Endpoint Routers
│   │   │   ├── schemas/    # Pydantic Request/Response Data Contracts
│   │   │   └── services/   # WorkflowEngine, CalculationService, DocumentTemplates
│   └── ui/             # 12 HTML Portals, CSS Stylesheets, and Core JavaScript
├── tests/              # 33 Pytest Test Suites (219 tests)
└── docs/               # 18 Standardized System Technical Documents
```

---

## 2. Backend Files (`src/backend/app/`)

### 2.1. Core Application & Configuration

| File Path | Main Responsibility | Key Symbols / Classes | Callers / Dependents | Dependencies | Feature Supported | Status |
|---|---|---|---|---|---|---|
| [`src/backend/run.py`](file:///home/nemro/RECRM/src/backend/run.py) | Application server launcher. Starts Uvicorn with auto-reload. | `APP_DIR`, `if __name__ == '__main__': uvicorn.run()` | Called by `start_server.sh` or manual CLI. | `uvicorn`, `app.config.settings` | System startup | **ACTIVE** |
| [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py) | FastAPI application factory, middleware, router mounting, lifespan. | `app`, `lifespan()`, `reservation_expiry_worker()`, `add_correlation_id_and_security_headers()` | Called by Uvicorn. | `FastAPI`, `CORSMiddleware`, `StaticFiles`, all 16 routers. | App lifecycle, middleware, background workers | **ACTIVE** |
| [`src/backend/app/config.py`](file:///home/nemro/RECRM/src/backend/app/config.py) | Typesafe environment configuration and PostgreSQL DSN URLs. | `Settings`, `settings`, `database_url`, `asyncpg_dsn` | Imported by `database.py`, `main.py`, `run.py`, and test suites. | `pydantic_settings.BaseSettings`, `.env` | System configuration | **ACTIVE** |
| [`src/backend/app/database.py`](file:///home/nemro/RECRM/src/backend/app/database.py) | Connection pool management and sequence-based ID generation. | `pool`, `init_db_pool()`, `close_db_pool()`, `get_db()`, `get_next_id()` | Injected via `Depends(get_db)` across all routers and test suites. | `asyncpg`, `app.config.settings` | Data persistence & connection pooling | **ACTIVE** |

---

### 2.2. Domain Services (`src/backend/app/services/`)

| File Path | Main Responsibility | Key Symbols / Classes | Callers / Dependents | Dependencies | Feature Supported | Status |
|---|---|---|---|---|---|---|
| [`src/backend/app/services/workflow_engine.py`](file:///home/nemro/RECRM/src/backend/app/services/workflow_engine.py) | Central business rules engine, state machine, SOP transitions, reservation expiry, gated cancellations. | `WorkflowEngine`, `on_lead_qualified()`, `schedule_property_viewing()`, `create_unit_reservation()`, `complete_task_with_outcome()`, `reopen_task()`, `cancel_task()`, `initiate_deal_cancellation()` | Called by `sales.py`, `leads.py`, `communications.py`, `management.py`, `main.py`. | `asyncpg`, `app.database`, `CalculationService`, `DocumentTemplates` | End-to-end operational workflows | **ACTIVE** |
| [`src/backend/app/services/calculation_service.py`](file:///home/nemro/RECRM/src/backend/app/services/calculation_service.py) | Mathematical calculations for Saudi real estate, commissions, taxes, and investments. | `CalculationService`, `calculate_rental_metrics()`, `calculate_investment_returns()`, `estimate_technical_capex_and_adjustment()`, `calculate_commission()`, `calculate_agent_commission()` | Called by `WorkflowEngine`, `calculations.py`, `finance.py`, `investment.py`. | Pure Python mathematical functions | Financial accuracy & compliance | **ACTIVE** |
| [`src/backend/app/services/document_templates.py`](file:///home/nemro/RECRM/src/backend/app/services/document_templates.py) | HTML rendering engine for authentic Saudi real estate documents. | `render_due_diligence_report()`, `render_commercial_offer()`, `render_invoice_document()`, `render_contract_document()`, `render_reservation_document()` | Called by `documents.py`, `WorkflowEngine.archive_workflow_document()`. | Pure Python string templates & CSS | Official printable documents | **ACTIVE** |

---

### 2.3. API Routers (`src/backend/app/routers/`)

| File Path | Main Responsibility | Key Endpoints | Dependencies | Feature Supported | Status |
|---|---|---|---|---|---|
| [`auth.py`](file:///home/nemro/RECRM/src/backend/app/routers/auth.py) | Authentication, user profile, role-based data scoping. | `GET /me`, `GET /auth/users`, `resolve_data_scope_filter()`, `check_user_scope_override()` | `app.database`, `users`, `roles`, `permissions` | RBAC & Data Isolation | **ACTIVE** |
| [`sales.py`](file:///home/nemro/RECRM/src/backend/app/routers/sales.py) | Sales pipeline, deals Kanban, viewings, offers, unit reservations, gated deal cancellation. | `GET /opportunities`, `PATCH /opportunities/{id}`, `POST /opportunities/{id}/cancel`, `POST /opportunities/{id}/reserve` | `WorkflowEngine`, `app.schemas.sales` | Sales & Deal Pipeline | **ACTIVE** |
| [`leads.py`](file:///home/nemro/RECRM/src/backend/app/routers/leads.py) | Lead intake, qualification, matching candidate units, lead reassignment. | `GET /leads`, `POST /leads`, `GET /leads/{id}/matched-units`, `POST /leads/{id}/qualify` | `WorkflowEngine`, `CalculationService`, `app.schemas.leads` | Lead Management | **ACTIVE** |
| [`communications.py`](file:///home/nemro/RECRM/src/backend/app/routers/communications.py) | Tasks list, activities audit log, communications feed, task complete/reopen/cancel. | `GET /tasks`, `POST /tasks/{id}/complete`, `POST /tasks/{id}/reopen`, `POST /tasks/{id}/cancel`, `GET /activities` | `WorkflowEngine`, `app.schemas.communications` | Tasks & Audit Trail | **ACTIVE** |
| [`customers.py`](file:///home/nemro/RECRM/src/backend/app/routers/customers.py) | Customer CRUD, 360 profile, interaction history. | `GET /customers`, `POST /customers`, `GET /customers/{id}/360` | `app.database`, `app.schemas.customers` | Customer 360 | **ACTIVE** |
| [`properties.py`](file:///home/nemro/RECRM/src/backend/app/routers/properties.py) | Real estate inventory: projects, buildings, units, media, status tracking. | `GET /properties/units`, `POST /properties/units`, `GET /properties/buildings`, `GET /properties/projects` | `app.database`, `app.schemas.properties` | Inventory Management | **ACTIVE** |
| [`finance.py`](file:///home/nemro/RECRM/src/backend/app/routers/finance.py) | Invoices, payments, receipts, broker commissions, agent earnings. | `GET /finance/invoices`, `POST /finance/invoices`, `POST /finance/payments`, `GET /finance/commissions` | `CalculationService`, `WorkflowEngine`, `app.schemas.finance` | Billing & Accounting | **ACTIVE** |
| [`management.py`](file:///home/nemro/RECRM/src/backend/app/routers/management.py) | Tenancies, rent collection schedule, maintenance tickets, work orders, owner yields. | `POST /management/tenancies`, `GET /management/rent-collections`, `POST /management/tickets`, `GET /management/owner-yields` | `WorkflowEngine`, `app.schemas.management` | Property & Facility Mgmt | **ACTIVE** |
| [`documents.py`](file:///home/nemro/RECRM/src/backend/app/routers/documents.py) | Document repository, generation, HTML preview, document access logging. | `GET /documents`, `GET /documents/{id}/preview`, `POST /documents/generate` | `DocumentTemplates`, `app.schemas.documents` | Document Archive | **ACTIVE** |
| [`investment.py`](file:///home/nemro/RECRM/src/backend/app/routers/investment.py) | Technical due diligence inspections, structural/HVAC audits, CapEx discounts. | `POST /investment/due-diligence`, `GET /investment/due-diligence/{id}` | `CalculationService`, `WorkflowEngine` | Investment Advisory | **ACTIVE** |
| [`calculations.py`](file:///home/nemro/RECRM/src/backend/app/routers/calculations.py) | Interactive financial calculators (Yield, Cap Rate, Mortgage, RETT, Commissions). | `POST /calculate/rental-yield`, `POST /calculate/investment-returns`, `POST /calculate/commission` | `CalculationService`, `app.schemas.calculations` | Financial Calculators | **ACTIVE** |
| [`reports.py`](file:///home/nemro/RECRM/src/backend/app/routers/reports.py) | Executive & managerial reporting, SLA metrics, agent conversion KPIs. | `GET /reports/dashboard-kpis`, `GET /reports/agent-performance`, `GET /reports/sla-compliance` | `CalculationService`, `app.schemas.reports` | Analytics & KPIs | **ACTIVE** |
| [`marketing.py`](file:///home/nemro/RECRM/src/backend/app/routers/marketing.py) | Ad campaigns, marketing channels, lead source attribution. | `GET /marketing/campaigns`, `POST /marketing/campaigns`, `GET /marketing/attribution` | `app.schemas.marketing` | Marketing Attribution | **ACTIVE** |
| [`listings.py`](file:///home/nemro/RECRM/src/backend/app/routers/listings.py) | Public property syndication listings and portal publishing. | `GET /listings`, `POST /listings`, `PATCH /listings/{id}/publish` | `app.schemas.listings` | Syndication & Listings | **ACTIVE** |
| [`admin.py`](file:///home/nemro/RECRM/src/backend/app/routers/admin.py) | User management, roles, permissions, branches, audit log viewing. | `GET /admin/users`, `POST /admin/users`, `GET /admin/roles`, `GET /admin/audit-logs` | `app.schemas.admin` | Governance & Security | **ACTIVE** |
| [`reference.py`](file:///home/nemro/RECRM/src/backend/app/routers/reference.py) | Reference lookups (cities, property types, loss reasons, activity types). | `GET /cities`, `GET /property-types`, `GET /loss-reasons`, `GET /activity-types` | `app.database` | System Lookups | **ACTIVE** |

---

## 3. Frontend Files (`src/ui/`)

| File Path | Description & Page Role | Key Functions / Elements | Associated Backend Routers | Status |
|---|---|---|---|---|
| [`src/ui/index.html`](file:///home/nemro/RECRM/src/ui/index.html) | **Dashboard**: High-level KPIs, personal workspace, recent deals and leads. | `loadDashboardKPIs()`, `renderPersonalWorkspace()`, `toggleLanguage()` | `reports.py`, `sales.py`, `leads.py`, `communications.py` | **ACTIVE** |
| [`src/ui/customers.html`](file:///home/nemro/RECRM/src/ui/customers.html) | **Customers 360**: Unified buyer, tenant, landlord database with transaction history. | `loadCustomers()`, `openCustomer360Modal()`, `handleCreateCustomer()` | `customers.py` | **ACTIVE** |
| [`src/ui/leads.html`](file:///home/nemro/RECRM/src/ui/leads.html) | **Leads Management**: Lead pipeline, SLA countdowns, unit matchmaker. | `loadLeads()`, `openNewLeadModal()`, `viewMatchedUnits()` | `leads.py`, `properties.py` | **ACTIVE** |
| [`src/ui/properties.html`](file:///home/nemro/RECRM/src/ui/properties.html) | **Inventory Management**: Projects, Buildings, Units catalog with status badges. | `loadUnits()`, `openNewUnitModal()`, `filterProperties()` | `properties.py`, `reference.py` | **ACTIVE** |
| [`src/ui/sales.html`](file:///home/nemro/RECRM/src/ui/sales.html) | **Sales Pipeline Board**: Kanban stages, viewings, offers, unit reservation, cancellation modal. | `renderPipeline()`, `openCancelOpportunityModal()`, `openReserveUnitModal()` | `sales.py`, `properties.py`, `finance.py` | **ACTIVE** |
| [`src/ui/finance.html`](file:///home/nemro/RECRM/src/ui/finance.html) | **Finance & Billing**: ZATCA tax invoices, receipt vouchers, broker commissions. | `loadInvoices()`, `openPaymentModal()`, `renderCommissions()` | `finance.py` | **ACTIVE** |
| [`src/ui/management.html`](file:///home/nemro/RECRM/src/ui/management.html) | **Property Management**: Tenancy contracts, rent schedules, maintenance tickets, work orders, owner yields. | `loadTenancies()`, `openNewTicketModal()`, `openWorkOrderModal()`, `loadYields()` | `management.py` | **ACTIVE** |
| [`src/ui/tasks.html`](file:///home/nemro/RECRM/src/ui/tasks.html) | **Tasks & Communications**: Agent to-dos, activities audit trail, smart reopen, cancel warning modal, SOP guidance. | `loadTasks()`, `completeTask()`, `promptReopenTask()`, `openCancelTaskModal()`, `openSopHelpModal()` | `communications.py` | **ACTIVE** |
| [`src/ui/documents.html`](file:///home/nemro/RECRM/src/ui/documents.html) | **Document Repository**: Document archive, HTML print preview, doc generator. | `loadDocuments()`, `previewDocument()`, `submitGenerateDocument()` | `documents.py` | **ACTIVE** |
| [`src/ui/campaigns.html`](file:///home/nemro/RECRM/src/ui/campaigns.html) | **Marketing Campaigns**: Ad performance, channel conversion, lead attribution. | `loadCampaigns()`, `openNewCampaignModal()`, `renderAttributionChart()` | `marketing.py` | **ACTIVE** |
| [`src/ui/listings.html`](file:///home/nemro/RECRM/src/ui/listings.html) | **Property Listings**: Syndication management and public property marketing. | `loadListings()`, `togglePublishStatus()`, `openNewListingModal()` | `listings.py`, `properties.py` | **ACTIVE** |
| [`src/ui/admin.html`](file:///home/nemro/RECRM/src/ui/admin.html) | **System Administration**: Employee users, RBAC roles, permissions, audit log viewer. | `loadUsers()`, `openNewUserModal()`, `loadAuditLogs()`, `renderPermissions()` | `admin.py`, `auth.py` | **ACTIVE** |
| [`src/ui/common.js`](file:///home/nemro/RECRM/src/ui/common.js) | **Shared UI Library**: Centralized `apiRequest()`, Toast notifications, formatting. | `showToast()`, `apiRequest()`, `formatSAR()`, `formatArabicDate()` | Loaded by all 12 HTML pages. | **ACTIVE** |
| [`src/ui/user_session.js`](file:///home/nemro/RECRM/src/ui/user_session.js) | **User Session & RBAC**: Injects `X-User-ID`, user switcher widget, page permission checks. | `getCurrentUserProfile()`, `switchActiveUserContext()`, `PAGE_ACCESS_MAP` | Loaded by all 12 HTML pages. | **ACTIVE** |

---

## 4. Maintenance Scripts (`scripts/`)

| Script File | Purpose & Responsibility | Usage Command | Status |
|---|---|---|---|
| [`scripts/reset_database.py`](file:///home/nemro/RECRM/scripts/reset_database.py) | Safely wipes operational test data (Leads, Deals, Invoices, Tasks) while preserving Users, Branches, and Lookups. | `python scripts/reset_database.py --mode crm --yes` | **ACTIVE** |
| [`scripts/migrate_stage2_schema.py`](file:///home/nemro/RECRM/scripts/migrate_stage2_schema.py) | Creates Stage 2 tables: `tenancies`, `maintenance_tickets`, `maintenance_work_orders`, `rent_collections`, `owner_yield_distributions`. | `python scripts/migrate_stage2_schema.py` | **ACTIVE** |
| [`scripts/migrate_cancellation_workflow.py`](file:///home/nemro/RECRM/scripts/migrate_cancellation_workflow.py) | Seeds templates and SOP guidance for gated financial settlement and inventory release. | `python scripts/migrate_cancellation_workflow.py` | **ACTIVE** |
| [`scripts/migrate_ids.py`](file:///home/nemro/RECRM/scripts/migrate_ids.py) | Migrates raw integer IDs to business-friendly prefixed sequential strings (`lead-12`, `opportunity-5`). | `python scripts/migrate_ids.py` | **ACTIVE** |
| [`scripts/migrate_internal_task_pings.py`](file:///home/nemro/RECRM/scripts/migrate_internal_task_pings.py) | Creates `internal_task_pings` table, composite indexes, and seeds initial operational reminder pings. | `python scripts/migrate_internal_task_pings.py` | **ACTIVE** |
| [`scripts/switch_db.py`](file:///home/nemro/RECRM/scripts/switch_db.py) | Utility to switch `.env` database connection between local test and development databases. | `python scripts/switch_db.py` | **ACTIVE** |
| [`scripts/deduplicate_unit_documents.py`](file:///home/nemro/RECRM/scripts/deduplicate_unit_documents.py) | Scans and deletes duplicate documents generated during automated test runs. | `python scripts/deduplicate_unit_documents.py` | **ACTIVE** |

---

## 5. Automated Test Suites (`tests/`)

All 33 test files in [`tests/`](file:///home/nemro/RECRM/tests) are **ACTIVE** and executed by Pytest:

1. `test_agenda_and_financial_schedules.py`: Calendar agenda query scoping and scheduled financial receivables notebook.
2. `test_agent_compensation_and_gov_fees.py`: Broker commissions, VAT, RETT, and agent salary tiers.
3. `test_calculation_service.py`: Yield, NOI, Cap Rate, and multi-factor matching equations.
4. `test_cancellation_workflows.py`: Gated deal cancellation, remediation task spawning, and auto-finalization.
5. `test_concurrency_controls.py`: Row-level locking on unit reservation.
6. `test_customer_business_rules.py`: Purpose-based routing, customer 360 isolation, and Ejar rent schedules.
7. `test_dynamic_workflow_transitions.py`: Outcome-based state machine task transitions.
8. `test_health_and_security.py`: `/health` endpoints and HTTP security headers.
9. `test_internal_task_pings.py`: Role-scoped internal chat reminder pings, inbox filtering, archiving as proof, and retention purging.
10. `test_investment_due_diligence_inspection.py`: Structural, HVAC, elevator, and CapEx inspection scoring.
11. `test_investment_workflow.py`: Investment asset acquisition and baseline financial sheets.
12. `test_manager_scoping_leads.py`: Branch sales manager scoping boundaries.
13. `test_managerial_kpis.py` & `test_managerial_kpis_scoping.py`: Executive KPI aggregation and branch scoping.
14. `test_pages_database_fetch.py`: Verifies all 12 HTML pages fetch valid backend responses.
15. `test_properties_and_inventory.py`: Units, buildings, and projects CRUD.
16. `test_rbac_and_scoping.py`: Multi-role access control and query scoping verification.
17. `test_rental_workflow.py`: End-to-end rental lease cycle from lead to tenancy.
18. `test_saudi_fees_and_invoices.py`: ZATCA tax invoice generation and fee verification gating before winning deals.
19. `test_situation_and_unblock.py`: 1-click diagnostic and unblocking of stalled transactions.
20. `test_smart_reopen.py`: Undo functionality and safe rollback of downstream tasks.
21. `test_sop_guidance.py`: SOP instructions and checklist retrieval.
22. `test_stage2_operations.py`: Property management, tickets, work orders, and owner yields.
23. `test_task_row_selection_and_insertion.py`: Ad-hoc task insertion into live workflow journeys.
24. `test_unit_matching_inquiry.py`: Match score ranking of units against lead criteria.
25. `test_users_permissions_and_scoping.py`: User authorization and role resolution.
26. `test_viewings_and_history.py`: Viewing appointment scheduling and feedback logging.
27. `test_workflow_catalog_alignment.py`: Verifies all templates align with the Workflow Catalog.
28. `test_workflow_documents_and_decision_support.py`: In-memory document generation and preview.
29. `test_workflow_stage1.py`, `stage2.py`, `stage3.py`, `stages_e_f_g.py`: Complete transactional lifecycle stages.

