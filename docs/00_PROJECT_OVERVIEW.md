# 00. Project Overview: RECRM Platform
### نظرة عامة على النظام — مكتب معاذ خضر النمري للخدمات العقارية

---

## 1. What is RECRM?

**RECRM** is a specialized real estate software platform created for real estate brokerages, facility management firms, and property investment offices operating in the Kingdom of Saudi Arabia. 

In everyday terms, real estate companies have to keep track of hundreds of moving pieces:
- People calling in looking to rent an apartment or buy a villa.
- Property owners listing their buildings and commercial spaces.
- Viewing appointments where agents show properties to prospects.
- Reservation deposits (`عربون`) that must be held securely under strict government rules.
- Government-mandated taxes, such as the Real Estate Transaction Tax (**RETT** / ضريبة التصرفات العقارية) and Value Added Tax (**VAT**).
- Tenancy contracts registered according to the national **Ejar** (إيجار) framework.
- Ongoing property management: rent collection, plumbing/electrical maintenance tickets, and sending earnings to property owners.

Before RECRM, brokerages typically relied on Excel spreadsheets, paper forms, and WhatsApp messages. This led to lost leads, double-booked units, missed rent collections, and non-compliance with Saudi real estate laws. 

**RECRM solves this by giving every employee a single, unified digital office** where every action—from an incoming lead to the final bank deposit—is tracked, audited, and governed by automated business rules.

---

## 2. Who Uses RECRM?

RECRM is designed for several distinct job roles within a real estate office:

| Role | Title in Arabic | Primary Responsibilities in RECRM |
|---|---|---|
| **System Administrator** | مدير النظام التقني | Manages system configuration, creates user accounts, monitors audit logs, and handles data security. |
| **General Manager** | المدير العام | Reviews company-wide KPIs, overall sales performance, financial revenue, and branch-by-branch conversion rates. |
| **Branch Sales Manager** | مدير مبيعات الفرع | Oversees a team of agents in a specific city/branch, reassigns overdue tasks, and approves commercial offers. |
| **Sales Agent** | وسيط مبيعات | Manages purchase and investment inquiries, conducts property tours, negotiates offers, and locks unit reservations. |
| **Leasing Agent** | وسيط تأجير | Matches tenants with rental apartments/shops, drafts tenancy agreements, and coordinates move-in dates. |
| **Property & Facility Manager** | مدير الأملاك والمرافق | Oversees managed buildings, logs tenant maintenance tickets, assigns repair work orders to vendors, and tracks unit handovers. |
| **Accountant** | محاسب مالي | Issues official ZATCA tax invoices, tracks SADA/bank receipt vouchers, calculates broker commissions, and executes yield distributions. |
| **Document Controller** | مسؤول الأرشفة والوثائق | Audits electronic title deeds, verifies seller disclosure forms, reviews Taqeem valuation reports, and clears contracts. |
| **Marketing Specialist** | أخصائي تسويق | Launches property ad campaigns on social media and portals, monitors campaign ROI, and tracks lead acquisition channels. |
| **Auditor / Compliance Officer** | مراقب الامتثال والحوكمة | Has read-only global access to verify adherence to Saudi Real Estate General Authority (REGA) regulations and tax compliance. |

---

## 3. Existing Modules (The 12 Portals)

The application frontend is organized into 12 dedicated, single-page portals accessible from the unified top navigation bar:

```
[1. Dashboard]  [2. Customers 360]  [3. Leads]     [4. Properties]  [5. Sales Pipeline]  [6. Finance]
[7. Management] [8. Tasks & SOPs]   [9. Documents] [10. Campaigns]  [11. Listings]       [12. Admin]
```

1. **Dashboard & KPIs (`index.html`)**: Live summary metrics (leads, viewings, pipeline value, open tasks, collections), personal workspace, and quick navigation.
2. **Customers 360 (`customers.html`)**: Complete buyer/tenant/landlord profiles with full transaction histories, anti-duplication logic, and interaction timelines.
3. **Leads Management (`leads.html`)**: Tracks incoming prospective clients, initial contact SLA timers (30 minutes), and qualifications.
4. **Properties & Inventory (`properties.html`)**: Detailed catalog of Projects, Buildings, and Individual Units with status badges (`AVAILABLE`, `RESERVED`, `SOLD`, `RENTED`).
5. **Sales Pipeline & Deals (`sales.html`)**: Interactive Kanban board (Qualified ➔ Viewing ➔ Offer ➔ Won / Lost) with 48h reservation timers and gated cancellation controls.
6. **Finance & Contracts (`finance.html`)**: Billing engine managing 2.5% brokerage fees, 15% VAT, 5% RETT notices, receipt vouchers, and agent commission payouts.
7. **Property & Facility Management (`management.html`)**: Active leases, automated installment schedules, maintenance tickets, contractor work orders, and periodic owner yield payouts.
8. **Tasks, Activities & SOPs (`tasks.html`)**: Action center displaying assigned tasks, step-by-step SOP guides, smart reopen/undo buttons, and a complete communication audit log.
9. **Documents & Files (`documents.html`)**: Document repository with in-browser printable preview for contracts, Taqeem valuations, and due diligence reports.
10. **Marketing & Campaigns (`campaigns.html`)**: Ad campaign performance, channel lead attribution, and cost-per-lead tracking.
11. **Property Listings (`listings.html`)**: Syndication portal preparing listings for public display and real estate portals.
12. **Admin & Governance (`admin.html`)**: System user management, role assignments, permissions matrix, branch configurations, and security audit log viewer.

---

## 4. Current Implementation Status

### A. Fully Implemented & Verified Capabilities (`IMPLEMENTED`)
- **Core Workflow Engine**: Complete state machine handling over 25 distinct task templates, dynamic transitions, and task auto-generation.
- **Purpose-Based Qualification**: Automatic routing of leads into **RENT**, **BUY**, or **INVESTMENT** workflows.
- **Smart Reopen & Undo**: Capability to undo an accidentally completed task, which safely rolls back any scheduled downstream viewings or tasks.
- **Concurrency Locking**: Row-level locking (`SELECT ... FOR UPDATE`) preventing two agents from reserving the same unit at the exact same instant.
- **48-Hour Reservation Deposit SLA**: Background worker that monitors reservations awaiting earnest deposits (`عربون`) and automatically releases the unit if unpaid.
- **Gated Deal & Task Cancellation**: Structured cancellation workflow where deals with open financial liabilities or held assets cannot be cancelled until remediation tasks (refunds, credit notes, inventory release) are verified complete.
- **Saudi Real Estate Math**: Accurate calculation of gross/net rental yields, NOI, Cap Rate, Cash-on-Cash Return, CapEx technical defect discounts, and REGA-compliant agent commissions.
- **Bilingual Interface**: Native Arabic (RTL) and English (LTR) language toggle on all 12 operational screens.
- **100% Test Coverage**: All 198 automated integration tests pass cleanly with zero orphaned database test records.

### B. Partially Implemented Capabilities (`PARTIALLY IMPLEMENTED`)
- **ZATCA E-Invoicing**: Generates standard ZATCA-compliant tax invoice layouts, line items, and QR codes; however, direct API integration with the ZATCA Fatoora Phase 2 portal is currently simulated locally.
- **Ejar Platform Integration**: Tenancy agreements, payment frequencies, and unit terms conform to Ejar standards, but contract pushing is handled via internal workflows rather than a live government REST webhook.
- **Communications Feed**: In-app telephone, WhatsApp, and email interactions are logged and tracked internally; live telephony gateway integration (e.g. Twilio/Unifonic) is not yet wired to live telecoms.

### C. Missing Capabilities Identified During Review (`NOT IMPLEMENTED`)
- **Native Mobile Application**: The system is fully responsive for mobile browsers, but there is no dedicated iOS or Android Swift/Kotlin app.
- **Direct Online Card Checkout**: The system issues invoices and records bank transfers, cash receipts, and SADA references, but does not yet integrate an embedded card checkout widget (Mada/Visa/ApplePay) for end-customers.
- **Automated Property Portal Syndication**: Property listings can be prepared and exported, but automatic bidirectional API syndication with third-party portals (Aqar, Bayut) is not yet active.

---

## 5. Main Technologies at a Glance

```text
[ Client Browser ]
        │  Pure HTML5 / CSS3 / Vanilla JS (Cairo & Tajawal Fonts)
        │  Fetch API with JSON Envelopes & X-User-ID Session Headers
        ▼
[ FastAPI Application (Python 3.14 / 3.12) ]
        │  Uvicorn ASGI Server (Port 8000)
        │  Pydantic Schemas & Request Validation
        │  WorkflowEngine & CalculationService
        ▼
[ asyncpg Native Driver ]
        │  Async Connection Pool (2 to 20 connections)
        ▼
[ PostgreSQL Database (re_db) ]
        53 Relational Tables & 45 Sequences
```

---

## 6. High-Level Architecture

RECRM follows an **Asynchronous Monolithic Service Architecture**:
1. **Frontend Layer**: Built without heavyweight frameworks (zero React/Vue/Node.js dependencies). Each of the 12 portals is an independent HTML file that loads shared styles and libraries (`common.js`, `user_session.js`). This ensures zero build time, instantaneous loading, and effortless debugging.
2. **API & Business Layer**: Built with **FastAPI**. Requests are validated using **Pydantic** schemas, authenticated using an **RBAC session resolver**, and processed by dedicated domain services (`WorkflowEngine`, `CalculationService`, `DocumentTemplates`).
3. **Data Layer**: Powered by **PostgreSQL** accessed directly via **asyncpg**. RECRM avoids traditional ORM overhead (like Django ORM or Hibernate) in favor of high-performance parameterized SQL queries, explicit transaction boundaries, and PostgreSQL-level sequences.

---

## 7. Important Limitations for Beginners to Know

1. **Authentication Mechanism**: Currently, user authentication is managed via an `X-User-ID` HTTP header passed by the frontend rather than encrypted JWT tokens or HTTP-only cookies. While ideal for local office intranet development and testing, production public deployment will require adding JWT/OAuth2 tokens.
2. **Document Storage**: Generated documents (invoices, reports, contracts) are generated on the fly as clean, printable HTML and logged in database tables (`documents`, `document_access_log`). They are not currently uploaded to external cloud object storage (such as AWS S3).
3. **Background Tasks**: Scheduled jobs (such as the 60-second reservation expiry worker) run as an in-process `asyncio.create_task` inside the FastAPI lifespan rather than a separate distributed queue like Celery or Redis. This makes deployment simple on a single server, but requires a single instance of the background worker.

