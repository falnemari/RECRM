# 05. Modules & Features Specification
### المواصفات التفصيلية للوحدات والوظائف التشغيلية

This document provides a granular specification of every functional module and capability within **RECRM**, using standardized evaluation criteria and implementation statuses.

---

## Standard Implementation Statuses
- **`IMPLEMENTED`**: Fully verified in the codebase and backed by automated tests.
- **`PARTIALLY IMPLEMENTED`**: Core logic exists, but some aspects (e.g. external government APIs) are simulated locally.
- **`NOT IMPLEMENTED`**: Absent from the codebase.
- **`UNVERIFIED`**: Code exists, but runtime behavioral confirmation is pending.
- **`PLANNED`**: Formally specified in roadmap documentation for future phases.

---

## Module 1: Customer Relationship Management (Customers 360)

### 1.1. Unified Customer Profile & Anti-Duplication
1. **Feature Name**: Unified Customer Profile & Anti-Duplication (`find_or_create_customer`)
2. **Business Purpose**: Consolidate every client's history (as buyer, seller, tenant, or investor) under a single record to prevent fragmented communication and duplicate sales calls.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `ACCOUNTANT`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/customers.html`](file:///home/nemro/RECRM/src/ui/customers.html), Customer 360 Drawer, New Customer Modal.
5. **Backend Endpoints / Handlers**: `GET /api/v1/customers`, `POST /api/v1/customers`, `GET /api/v1/customers/{id}/360` in [`src/backend/app/routers/customers.py`](file:///home/nemro/RECRM/src/backend/app/routers/customers.py).
6. **Business Logic & Services**: [`WorkflowEngine.find_or_create_customer`](file:///home/nemro/RECRM/src/backend/app/services/workflow_engine.py#L141). Normalizes Saudi mobile numbers (`+9665...`) and searches for matching mobile or email before creating a new record.
7. **Database Tables**: `customers`, `activities`, `leads`, `opportunities`, `contracts`, `invoices`, `tenancies`.
8. **Validation Rules**: Mobile must be a valid Saudi mobile format; email must be valid; customer type must be `INDIVIDUAL` or `CORPORATE`.
9. **Permissions**: `CUSTOMER_READ`, `CUSTOMER_WRITE`.
10. **Dependencies**: `asyncpg`, PostgreSQL sequence `seq_customers_id`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: National ID / Iqama number field is optional; automated Yakeen / Absher verification is not connected.

---

## Module 2: Lead Intake & Qualification

### 2.1. Purpose-Based Lead Qualification & Routing
1. **Feature Name**: Purpose-Based Lead Routing (RENT / BUY / INVEST)
2. **Business Purpose**: Automatically fork leads upon qualification into the appropriate business pipeline, creating transactions governed by relevant rules and tasks.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `MARKETING`.
4. **Frontend Pages / Components**: [`src/ui/leads.html`](file:///home/nemro/RECRM/src/ui/leads.html), New Lead Modal, Matched Units Flyout.
5. **Backend Endpoints / Handlers**: `POST /api/v1/leads`, `GET /api/v1/leads/{id}/matched-units`, `POST /api/v1/tasks/{id}/complete` in [`src/backend/app/routers/leads.py`](file:///home/nemro/RECRM/src/backend/app/routers/leads.py) and [`communications.py`](file:///home/nemro/RECRM/src/backend/app/routers/communications.py).
6. **Business Logic & Services**: `WorkflowEngine.on_lead_qualified()` forks into `RENT` (tenancy pipeline), `BUY` (sales pipeline), or `INVEST` (due diligence & returns analysis).
7. **Database Tables**: `leads`, `opportunities`, `tasks`, `workflow_templates`, `activities`.
8. **Validation Rules**: `budget_min <= budget_max`; valid `inquiry_type` (`RENT`, `BUY`, `INVEST`); required city and property type.
9. **Permissions**: `LEAD_READ`, `LEAD_WRITE`.
10. **Dependencies**: `CalculationService.check_property_eligibility()`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: If a customer inquires for both Rent and Buy at the exact same moment, two leads must be submitted.

### 2.2. First-Contact 30-Minute SLA Engine
1. **Feature Name**: Automated First-Contact Task & SLA Countdown
2. **Business Purpose**: Ensure rapid lead response within 30 minutes to maximize conversion rates and prevent lead leakage.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`.
4. **Frontend Pages / Components**: [`src/ui/tasks.html`](file:///home/nemro/RECRM/src/ui/tasks.html), Overdue Badge indicators.
5. **Backend Endpoints / Handlers**: `WorkflowEngine.on_lead_assigned()`, `WorkflowEngine.evaluate_sla_escalations()`.
6. **Business Logic & Services**: Sets `due_at = NOW() + INTERVAL '30 minutes'` on `TASK_FIRST_CONTACT`. Automatically escalates overdue tasks to the branch manager if untouched.
7. **Database Tables**: `tasks`, `workflow_templates`, `leads`.
8. **Validation Rules**: Cannot complete without selecting outcome (`CONNECTED`, `NO_ANSWER`, `WRONG_NUMBER`).
9. **Permissions**: `SALES_WRITE`.
10. **Dependencies**: `WorkflowEngine.spawn_task_from_template()`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Does not place automated outgoing VoIP phone calls directly through telecom carriers.

---

## Module 3: Inventory & Property Matching

### 3.1. Inventory Catalog & Multi-Level Directories (Projects, Buildings, Units)
1. **Feature Name**: Multi-Level Real Estate Directory & Unit Inventory with Live Duplication Prevention
2. **Business Purpose**: Maintain a single source of truth for all real estate assets across a hierarchical directory: Projects (المشاريع), Buildings/Compounds (المباني والعمائر), and Units (الوحدات). Provide cross-level navigation and live anti-duplication alerts to eliminate accidental re-entry of existing projects or buildings.
3. **User Roles**: `PROPERTY_MANAGER`, `SALES_AGENT`, `LEASING_AGENT`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/properties.html`](file:///home/nemro/RECRM/src/ui/properties.html), Navigation Tab Bar (`#prop-levels-tabs`: Units Inventory, Projects Directory, Buildings Directory), Projects Directory Grid (`#panel-projects`), Buildings Directory Grid (`#panel-buildings`), Add Project Modal (`#add-project-modal`) with live duplication warning alert, Add Building Modal (`#add-building-modal`) with live duplication warning alert, Add & Edit Unit Modals.
5. **Backend Endpoints / Handlers**:
   - `GET /api/v1/projects` (with `search`, `status`, `city_id` query filters; returns subquery counts for `buildings_count` and `units_count`, plus `developer_name` and `city_name_ar`).
   - `GET /api/v1/buildings` (with `search`, `project_id` query filters; returns subquery count for `units_count`).
   - `GET /api/v1/units` (with `search`, `project_id`, `building_id`, `status`, `listing_purpose`, `bedrooms`, `assigned_user_id` query filters).
   - `POST /api/v1/projects`, `POST /api/v1/buildings`, `POST /api/v1/units` in [`src/backend/app/routers/properties.py`](file:///home/nemro/RECRM/src/backend/app/routers/properties.py).
6. **Business Logic & Services**:
   - Multi-level hierarchical aggregation: projects compute aggregated building count and total unit count (including standalone land units and building units).
   - Live anti-duplication detection: Real-time Arabic text normalization (stripping tashkeel, unifying alefs `[أإآ]` to `ا`, `ة` to `ه`, `ى` to `ي`, normalizing spaces) to flag existing matching or similar projects/buildings as the broker types.
   - Cross-filtering: 1-click drill down from a project card to view its buildings or units, and from a building card to view its units.
7. **Database Tables**: `projects`, `buildings`, `units` (including `floor_no` for unit floor inside building, `total_floors` for whole asset floors count, and building association `building_id`), `property_types`, `unit_status_history`, `property_media`, `customers` (developers/owners).
8. **Validation Rules**: `asking_price >= 0`, `rent_price >= 0`, unique `unit_number` within a building, unique `building_code` within a project. Floor specification rule: `floor_no` is captured when unit belongs to a building, while `total_floors` is captured for whole assets (Villas, Duplexes, Townhouses, Standalone Buildings, Hotels/Hospitality, and multi-level Penthouses).
9. **Permissions**: `PROPERTY_READ`, `PROPERTY_WRITE`.
10. **Dependencies**: PostgreSQL sequence `seq_units_id`, `seq_projects_id`, `seq_buildings_id`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: 3D virtual tour rendering is not supported; media is stored as URL references.

### 3.2. Weighted Property Matching Algorithm
1. **Feature Name**: Multi-Factor Property Match Score ($S = \sum w_i s_i$)
2. **Business Purpose**: Automatically rank available units against lead criteria (budget, bedrooms, area, location).
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`.
4. **Frontend Pages / Components**: [`src/ui/leads.html`](file:///home/nemro/RECRM/src/ui/leads.html) (Matched Units modal).
5. **Backend Endpoints / Handlers**: `GET /api/v1/leads/{id}/matched-units`.
6. **Business Logic & Services**: [`CalculationService.calculate_property_match_score`](file:///home/nemro/RECRM/src/backend/app/services/calculation_service.py#L145) calculates a 0–100 score weighted on: Budget (30%), Location (25%), Size/Bedrooms (20%), Timing/Status (15%), Amenities (10%).
7. **Database Tables**: `units`, `leads`, `properties`.
8. **Validation Rules**: Hard exclusion of units outside the mandatory budget or in different cities.
9. **Permissions**: `LEAD_READ`.
10. **Dependencies**: `CalculationService`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Amenity matching relies on text keyword matching in `investment_notes` rather than an explicit multi-select tags table.

---

## Module 4: Sales Pipeline & Deal Governance

### 4.1. Concurrency-Controlled 48h Unit Reservation
1. **Feature Name**: Concurrency-Locked Unit Reservation & Deposit Tracking
2. **Business Purpose**: Prevent double-booking of high-demand units while giving serious buyers exactly 48 hours to deposit earnest money (`عربون`).
3. **User Roles**: `SALES_AGENT`, `SALES_MANAGER`, `ACCOUNTANT`.
4. **Frontend Pages / Components**: [`src/ui/sales.html`](file:///home/nemro/RECRM/src/ui/sales.html) (`#reserve-unit-modal`).
5. **Backend Endpoints / Handlers**: `POST /api/v1/opportunities/{id}/reserve` in [`src/backend/app/routers/sales.py`](file:///home/nemro/RECRM/src/backend/app/routers/sales.py).
6. **Business Logic & Services**: Row-level locking `SELECT ... FOR UPDATE` in `WorkflowEngine.create_unit_reservation`. Automatically unreserves unit if 48h SLA expires without verified deposit.
7. **Database Tables**: `reservations`, `units`, `unit_status_history`, `tasks`, `activities`.
8. **Validation Rules**: Unit must have status `AVAILABLE`; deposit amount must be positive.
9. **Permissions**: `SALES_WRITE`.
10. **Dependencies**: `reservation_expiry_worker` in [`src/backend/app/main.py`](file:///home/nemro/RECRM/src/backend/app/main.py#L20).
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Background worker checks every 60 seconds; exact second-level precision is not required for a 48h window.

### 4.2. Gated Deal & Task Cancellation with Mandatory Remediation
1. **Feature Name**: Gated Cancellation & Remediation Engine
2. **Business Purpose**: Ensure brokerages comply with Saudi commercial law and civil transactions code by prohibiting premature deal abandonment while unsettled invoices, deposits, or locked units exist.
3. **User Roles**: `SALES_AGENT`, `SALES_MANAGER`, `ACCOUNTANT`.
4. **Frontend Pages / Components**: `#modal-cancel-task` in [`src/ui/tasks.html`](file:///home/nemro/RECRM/src/ui/tasks.html), `#modal-cancel-opportunity` in [`src/ui/sales.html`](file:///home/nemro/RECRM/src/ui/sales.html).
5. **Backend Endpoints / Handlers**: `POST /api/v1/tasks/{id}/cancel`, `POST /api/v1/opportunities/{id}/cancel`, `PATCH /api/v1/opportunities/{id}`.
6. **Business Logic & Services**: `WorkflowEngine.initiate_deal_cancellation()` and `check_and_finalize_cancellation_if_ready()`. Spawns `TASK_DEAL_FINANCIAL_SETTLEMENT` (Accountant) and `TASK_DEAL_INVENTORY_RELEASE` (Sales Agent).
7. **Database Tables**: `opportunities`, `tasks`, `invoices`, `reservations`, `units`, `activities`, `loss_reasons`.
8. **Validation Rules**: Moving stage directly to `CLOSED_LOST` via PATCH is rejected (HTTP 400) if remediation tasks are open.
9. **Permissions**: `SALES_WRITE`.
10. **Dependencies**: `WorkflowEngine`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Credit notes are generated within RECRM; automatic push to ZATCA credit-note portal is simulated.

---

## Module 5: Finance, Invoicing & Saudi Taxes

### 5.1. Statutory Fee Invoicing (2.5% Brokerage, 15% VAT, 5% RETT)
1. **Feature Name**: Statutory Fee & Tax Calculator
2. **Business Purpose**: Automatically generate compliant brokerage invoices (capped at 2.5% per REGA), calculate 15% VAT, and issue 5% RETT tax notifications for buyers.
3. **User Roles**: `ACCOUNTANT`, `SALES_AGENT`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/finance.html`](file:///home/nemro/RECRM/src/ui/finance.html), Invoices Table, Payment Modal.
5. **Backend Endpoints / Handlers**: `GET /api/v1/finance/invoices`, `POST /api/v1/finance/invoices`, `POST /api/v1/finance/payments` in [`src/backend/app/routers/finance.py`](file:///home/nemro/RECRM/src/backend/app/routers/finance.py).
6. **Business Logic & Services**: [`WorkflowEngine.generate_saudi_fee_invoices`](file:///home/nemro/RECRM/src/backend/app/services/workflow_engine.py#L3331) and [`CalculationService.calculate_commission`](file:///home/nemro/RECRM/src/backend/app/services/calculation_service.py#L514).
7. **Database Tables**: `invoices`, `payments`, `commissions`, `contracts`, `opportunities`.
8. **Validation Rules**: Payment cannot exceed remaining balance; VAT rate is fixed at 15.0%; brokerage commission cannot exceed statutory 2.5% without explicit legal exemption.
9. **Permissions**: `PAYMENT_READ`, `PAYMENT_WRITE`.
10. **Dependencies**: `CalculationService`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: SADA invoice integration generates SADA reference numbers locally; live SADA payment gateway polling requires mock bank approval.

---

## Module 6: Property & Facility Management (Stage 2)

### 6.1. Tenancy Agreements & Rent Installment Schedules
1. **Feature Name**: Tenancy Management & Rent Collection Schedule (Ejar Standard)
2. **Business Purpose**: Track residential and commercial leases, calculate installment payment dates (annual, semi-annual, quarterly, monthly), and track tenant arrears.
3. **User Roles**: `PROPERTY_MANAGER`, `LEASING_AGENT`, `ACCOUNTANT`.
4. **Frontend Pages / Components**: [`src/ui/management.html`](file:///home/nemro/RECRM/src/ui/management.html) (Tenancies Tab & Rent Collections Tab).
5. **Backend Endpoints / Handlers**: `POST /api/v1/management/tenancies`, `GET /api/v1/management/rent-collections`, `POST /api/v1/management/rent-collections/{id}/pay` in [`src/backend/app/routers/management.py`](file:///home/nemro/RECRM/src/backend/app/routers/management.py).
6. **Business Logic & Services**: [`WorkflowEngine.execute_tenancy_agreement`](file:///home/nemro/RECRM/src/backend/app/services/workflow_engine.py#L2053) generates `rent_collections` rows according to `payment_frequency`.
7. **Database Tables**: `tenancies`, `rent_collections`, `units`, `customers`.
8. **Validation Rules**: `start_date < end_date`; installments count must match payment frequency (1, 2, 4, 12).
9. **Permissions**: `PM_WRITE`.
10. **Dependencies**: `WorkflowEngine`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Ejar contract numbers are entered manually or generated with internal format; direct automated webhook to Ejar's REST server is simulated.

### 6.2. Maintenance Tickets & Vendor Work Orders
1. **Feature Name**: Maintenance Work Order Dispatch & Cost Tracking
2. **Business Purpose**: Enable tenants and property managers to log maintenance issues, assign external contractors, approve repair CapEx/OpEx, and track resolution.
3. **User Roles**: `PROPERTY_MANAGER`, `ACCOUNTANT`, `VENDORS`.
4. **Frontend Pages / Components**: [`src/ui/management.html`](file:///home/nemro/RECRM/src/ui/management.html) (Maintenance Tab, Work Order Modal).
5. **Backend Endpoints / Handlers**: `POST /api/v1/management/tickets`, `POST /api/v1/management/work-orders` in `management.py`.
6. **Business Logic & Services**: Work orders track estimated vs. actual repair cost; expense is linked to property net operating income.
7. **Database Tables**: `maintenance_tickets`, `maintenance_work_orders`, `vendors`, `units`.
8. **Validation Rules**: Ticket must specify severity (`EMERGENCY`, `HIGH`, `MEDIUM`, `LOW`); vendor must be active.
9. **Permissions**: `PM_WRITE`.
10. **Dependencies**: `app.database`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Contractors do not have a dedicated external mobile portal; work order status is updated by the property manager.

### 6.3. Owner Yield Distributions
1. **Feature Name**: Periodic Landlord Yield & Payout Accounting
2. **Business Purpose**: Reconcile collected rent minus maintenance costs and management fees, generating payout records for property owners.
3. **User Roles**: `ACCOUNTANT`, `PROPERTY_MANAGER`, `GENERAL_MANAGER`.
4. **Frontend Pages / Components**: [`src/ui/management.html`](file:///home/nemro/RECRM/src/ui/management.html) (Yields Tab).
5. **Backend Endpoints / Handlers**: `GET /api/v1/management/owner-yields`, `POST /api/v1/management/owner-yields/calculate` in `management.py`.
6. **Business Logic & Services**: `CalculationService.calculate_rental_metrics()` computes Net Yield = $(TotalCollected - Expenses - ManagementFee) / Basis$.
7. **Database Tables**: `owner_yield_distributions`, `tenancies`, `rent_collections`, `maintenance_work_orders`.
8. **Validation Rules**: Payout amount cannot be negative without explicit loss acknowledgement.
9. **Permissions**: `PAYMENT_WRITE`.
10. **Dependencies**: `CalculationService`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Automated bank SARIE wire integration is not active; payouts are logged as bank wire references.

---

## Module 7: Real Estate Investment Advisory

### 7.1. Technical Due Diligence & CapEx Defect Price Adjustment
1. **Feature Name**: Due Diligence Inspection & Valuation Discount Model
2. **Business Purpose**: Quantify structural, MEP, HVAC, and elevator defects to calculate required Capital Expenditures (CapEx) and generate a legally supported counter-offer discount letter.
3. **User Roles**: `INVESTMENT_ADVISOR`, `SALES_AGENT`, `SALES_MANAGER`.
4. **Frontend Pages / Components**: Inspection Form in [`src/ui/tasks.html`](file:///home/nemro/RECRM/src/ui/tasks.html) (`modal-complete-task`), Document preview in [`documents.html`](file:///home/nemro/RECRM/src/ui/documents.html).
5. **Backend Endpoints / Handlers**: `POST /api/v1/investment/due-diligence`, `GET /api/v1/investment/due-diligence/{id}` in [`src/backend/app/routers/investment.py`](file:///home/nemro/RECRM/src/backend/app/routers/investment.py).
6. **Business Logic & Services**: [`CalculationService.estimate_technical_capex_and_adjustment`](file:///home/nemro/RECRM/src/backend/app/services/calculation_service.py#L362) aggregates estimated repair costs across 9 building subsystems and calculates the suggested purchase price reduction.
7. **Database Tables**: `investment_due_diligence_reports`, `units`, `opportunities`, `documents`.
8. **Validation Rules**: Subsystem condition scores must be between 1 and 5; commercial viability score between 0 and 100.
9. **Permissions**: `SALES_WRITE`, `DOCUMENT_WRITE`.
10. **Dependencies**: `DocumentTemplates.render_counter_offer_letter()`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Photo uploads for site inspection defects are stored as URLs rather than an in-app image compressor.

---

## Module 8: System Administration & Governance

### 8.1. Role-Based Scoping & Security Audit Logging
1. **Feature Name**: Data Scoping & Immutable Audit Trails
2. **Business Purpose**: Prevent unauthorized cross-branch or cross-agent data access, while maintaining a tamper-evident audit log of all system changes.
3. **User Roles**: `SYS_ADMIN`, `AUDITOR`.
4. **Frontend Pages / Components**: [`src/ui/admin.html`](file:///home/nemro/RECRM/src/ui/admin.html), Audit Logs tab.
5. **Backend Endpoints / Handlers**: `GET /api/v1/admin/audit-logs`, `GET /api/v1/admin/users`, `POST /api/v1/admin/users` in [`src/backend/app/routers/admin.py`](file:///home/nemro/RECRM/src/backend/app/routers/admin.py).
6. **Business Logic & Services**: [`auth.py: resolve_data_scope_filter`](file:///home/nemro/RECRM/src/backend/app/routers/auth.py#L31) enforces query-level scoping.
7. **Database Tables**: `audit_logs`, `document_access_log`, `users`, `roles`, `permissions`, `role_permissions`, `branches`.
8. **Validation Rules**: User must be active; email must be unique; role must exist in `roles`.
9. **Permissions**: `ADMIN`, `AUDIT_READ`.
10. **Dependencies**: `app.database`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: IP address resolution in `audit_logs` reflects the local proxy/host if running behind a reverse proxy without `X-Forwarded-For` parsing.

---

## Module 9: Operational Calendar & Financial Schedules (المفكرات التشغيلية والمالية)

### 9.1. Interactive Operational Calendar & Schedules Agenda (تقويم الأجندة والمواعيد)
1. **Feature Name**: Operational Calendar & Schedules Organizer (`/api/v1/reports/agenda-calendar`)
2. **Business Purpose**: Provide brokers, branch managers, and general managers with a unified calendar and timeline organizer consolidating unfinished, unexecuted tasks, viewings, reservations, periodic rent collections, and work orders that have explicit deadlines and dates (`uncompleted_only=true` by default), with explicit `lead_id`, `task_id`, `viewing_id`, and `reservation_id` identifiers.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `BRANCH_MANAGER`, `GENERAL_MANAGER`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/index.html`](file:///home/nemro/RECRM/src/ui/index.html) (`#agenda-calendar-section`), Monthly Interactive Calendar Grid, Agenda Timeline View, Event Priority Badges, Uncompleted Tasks Only toggle button.
5. **Backend Endpoints / Handlers**: `GET /api/v1/reports/agenda-calendar` in [`src/backend/app/routers/reports.py`](file:///home/nemro/RECRM/src/backend/app/routers/reports.py).
6. **Business Logic & Services**: Aggregates tasks, viewings, reservations, rent collections, work orders, and ad campaigns. By default, strictly excludes completed (`COMPLETED`), cancelled (`CANCELLED`), converted (`CONVERTED`), or paid (`PAID`) records, focusing exclusively on actionable items with scheduled deadlines (`due_at`, `scheduled_start`, `expires_at`, `due_date`). Automatically applies role-based data isolation (`OWN` for frontline agents, `BRANCH` for branch managers, `GLOBAL` for executives).
7. **Database Tables**: `tasks`, `viewings`, `reservations`, `rent_collections`, `maintenance_work_orders`, `campaigns`, `leads`, `opportunities`, `units`.
8. **Validation Rules**: ISO date parsing for `start_date` / `end_date`; strict enum validation on `event_type` (`TASK`, `VIEWING`, `RESERVATION`, etc.); boolean filter on `uncompleted_only`.
9. **Permissions**: `REPORTS_READ`, `TASK_READ`.
10. **Dependencies**: `asyncpg`, `app.database`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: External Google Calendar or Outlook 365 bi-directional sync is not enabled; events operate natively within RECRM.

### 9.2. Financial Dues & Collections Schedule (مفكرة وجدول المبالغ والتحصيلات)
1. **Feature Name**: Categorized Financial Dues & Receivables Schedule (`/api/v1/reports/financial-schedule`)
2. **Business Purpose**: Deliver an itemized financial organizer categorized by Deals/Leads (invoices and reservation deposits), Property Management (periodic rent collections and maintenance work orders), and Marketing Campaigns (ad budgets), complete with collection status indicators (`COLLECTED`, `PENDING`, `OVERDUE`, `CANCELLED`) and collection rate KPIs.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `BRANCH_MANAGER`, `ACCOUNTANT`, `GENERAL_MANAGER`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/index.html`](file:///home/nemro/RECRM/src/ui/index.html) (`#financial-schedule-section`), 5-card financial summary strip, category & status filter chips, interactive lead jump buttons.
5. **Backend Endpoints / Handlers**: `GET /api/v1/reports/financial-schedule` in [`src/backend/app/routers/reports.py`](file:///home/nemro/RECRM/src/backend/app/routers/reports.py).
6. **Business Logic & Services**: Real-time aggregation of financial obligations across invoices, reservation deposits, rent installments, maintenance expenses, and marketing campaigns. Automatically computes overdue days against Saudi current date, collection rate %, and respects user scoping.
7. **Database Tables**: `invoices`, `reservations`, `rent_collections`, `maintenance_work_orders`, `campaigns`, `leads`, `opportunities`, `customers`.
8. **Validation Rules**: Valid `category` (`DEALS_LEADS`, `PROPERTY_MANAGEMENT`, `MARKETING`) and `collection_status` enums.
9. **Permissions**: `REPORTS_READ`, `FINANCE_READ`.
10. **Dependencies**: `asyncpg`, `app.database`.
11. **Status**: **`IMPLEMENTED`**
12. **Known Limitations**: Payment gateway webhook automation (e.g. HyperPay, Moyasar) is simulated through internal status updates.

### 9.3. Unified Deal Selection & Cross-Section Synchronization (المزامنة الذكية بين مساحة العمل والمفكرات والمسار)
1. **Feature Name**: Synchronized Deal Inspector and Downstream Scope Cascading.
2. **Business Purpose**: Place the Personal Workspace and Deals Explorer directly above the Operational Calendar and Financial Schedule. When a broker or manager clicks on any deal or opportunity row (or clicks "🎯 تحديد ومسار 360°"), the system locks that deal into active focus and synchronizes all downstream sections:
   - **Personal Workspace**: Highlights the active deal row (`selected-deal-row`) and displays `#workspace-selected-deal-banner` with deal identifier, client name, expected value, and a one-click reset button.
   - **Operational Calendar & Agenda**: Displays `#agenda-deal-scope-banner` and filters tasks, viewings, and reservations to this exact deal (`lead_id` / `opportunity_id`), recalculating event counter badges.
   - **Financial Dues & Collections Schedule**: Displays `#fin-deal-scope-banner` and filters invoices, deposits, and dues belonging to this deal, dynamically recalculating the 5 ledger KPI cards.
   - **Lead Operational History & 360° Journey Audit**: Automatically loads and visualizes the full operational history, audit trail, and completed tasks for `lead_id`.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `BRANCH_MANAGER`, `GENERAL_MANAGER`, `SYS_ADMIN`.
4. **Frontend Architecture**: Managed via `dashboardState.selectedDeal` in [`src/ui/index.html`](file:///home/nemro/RECRM/src/ui/index.html), leveraging cached `rawEvents` / `rawItems` for instantaneous in-memory scoping, backed by server-side query filtering (`lead_id` and `opportunity_id` query params).
5. **Backend Endpoints**: Both `GET /api/v1/reports/agenda-calendar` and `GET /api/v1/reports/financial-schedule` support `lead_id: Optional[str]` and `opportunity_id: Optional[str]`.
6. **Status**: **`IMPLEMENTED`**

### 9.4. Calendar Grid Controls, Direct Navigation & Internal Task Reminders
1. **Feature Name**: Stabilized Calendar Grid, Role-Aware Entity Navigation, and Contextual Non-Destructive Task Reminders.
2. **Business Purpose**:
   - **Indicator Clarity**: Eliminated conflicting double border boxes on calendar cells (blue vs. green). Today is now elegantly denoted via a circular pill badge on the day number (`.cal-day-cell.today .cal-day-number`), while the selection indicator square belongs exclusively to the selected day (`.cal-day-cell.selected` with green outer border and soft green background).
   - **Smooth Day Selection & Cancellation**: Selecting any day smoothly moves the green border across cells without leaving ghost selections. Clicking the selected day again toggles selection off, complemented by a prominent clear button `[ ✕ إلغاء تصفية اليوم وعرض كافة المواعيد ]` and an active day filter chip in the calendar toolbar.
   - **Role-Aware Direct Entity Navigation (`navigateToEntityPage`)**: Clicking any task, viewing, reservation, invoice, rent collection, work order, or ad campaign automatically directs the user to its dedicated management page (`tasks.html`, `leads.html`, `sales.html`, `management.html`, `finance.html`, `campaigns.html`) with the specific record pre-focused via URL query parameters, guarded strictly by RBAC permissions (`window.canUserAccessPage`).
   - **Contextual Internal Task Reminder Messaging (Non-Destructive Chat Ping)**: Operational teams (brokers, sales agents, direct managers, accountants, and executives) can send instant reminder pings attached to any task, viewing, or financial row. These pings carry full row metadata snapshots (Record ID, Title, Customer, Amount, Assignee) without altering task status machines, SLA deadlines, or financial ledger balances.
3. **User Roles**: `SALES_AGENT`, `LEASING_AGENT`, `SALES_MANAGER`, `BRANCH_MANAGER`, `PROPERTY_MANAGER`, `ACCOUNTANT`, `GENERAL_MANAGER`, `SYS_ADMIN`.
4. **Frontend Pages / Components**: [`src/ui/index.html`](file:///home/nemro/RECRM/src/ui/index.html) (`#modal-internal-task-reminder`, `navigateToEntityPage`, `showCalendarDayDetails`, `clearCalendarDayFilter`).
5. **Status**: **`IMPLEMENTED`**




