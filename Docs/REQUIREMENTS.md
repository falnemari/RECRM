# REQUIREMENTS.md

# Real Estate CRM — Software Requirements Specification
**Version:** 1.0  
**Status:** Baseline specification aligned with the approved SRS/RFP and 47-table PostgreSQL baseline  
**Scope:** Saudi real-estate brokerage/agency + property-management company

## 1. Purpose and business goals
The system is a single operational platform for customer, lead, property, sales, leasing, property-management, maintenance, collections, communications, documents, marketing and security workflows.

### Business goals
1. Increase lead response speed and conversion through capture, deduplication, assignment and SLA control.
2. Provide a Customer 360 view across buyer, tenant, owner and investor relationships.
3. Maintain a reliable project → building → unit inventory hierarchy with current status and pricing.
4. Standardize lead-to-opportunity, viewing, offer, reservation and contract workflows.
5. Manage managed properties, tenancies, maintenance and rent collections in one workflow.
6. Provide management dashboards for sales, pipeline, inventory, agents, maintenance and collections.
7. Integrate with website, WhatsApp, messaging, telephony, property portals, accounting/ERP, identity/SSO, object storage, maps and applicable Saudi platforms.
8. Enforce least privilege, MFA, auditability, secure document handling, backup/DR and privacy controls.
9. Support Arabic/English and RTL/LTR experiences.

## 2. Scope and priorities
- **Must:** production/MVP requirement.
- **Should:** important phase-1/phase-2 requirement.
- **Could:** optional/future capability.

No approved business requirement may be silently changed. Any change requires a documented change request, reason, impact and approval.

## 3. User roles
| ID | Role | Primary responsibilities |
|---|---|---|
| R01 | System Administrator | Platform, integrations, security configuration |
| R02 | Executive/CEO | Executive dashboards and approved reports |
| R03 | Sales Director | Sales teams, pipeline, approvals, KPIs |
| R04 | Branch Manager | Branch leads, agents, inventory, activities |
| R05 | Sales Agent/Broker | Assigned leads, customers, units, viewings, offers |
| R06 | Property Manager | Owners, managed units, tenancies, maintenance, collections |
| R07 | Leasing Agent | Tenant lifecycle, viewings, leases |
| R08 | Maintenance Coordinator | Tickets, vendors, work orders |
| R09 | Finance | Payments, collections, commissions, reconciliation |
| R10 | Marketing | Campaigns, sources, attribution |
| R11 | Call Center | Lead capture, calls, appointment scheduling |
| R12 | Legal/Contracts | Contracts, documents, approvals |
| R13 | Auditor | Read-only audit/compliance access |

## 4. Functional requirements

### 4.1 CRM
- **REQ-CRM-001 Must:** Capture, deduplicate, qualify, assign and track leads from web, portals, phone, WhatsApp and manual entry.
- **REQ-CRM-002 Must:** Configurable response SLA, escalation and overdue alerts.
- **REQ-CRM-003 Must:** Unified Customer 360 for buyer/tenant/owner/investor profiles and interaction history.

### 4.2 Property inventory
- **REQ-PROP-001 Must:** Project/building/unit hierarchy with current unit status and pricing.
- **REQ-PROP-002 Must:** Create, publish, pause and expire listings while preserving external portal IDs.
- **REQ-PROP-003 Must:** Match customer criteria to available properties/units.

### 4.3 Sales
- **REQ-SALES-001 Must:** Configurable pipeline from qualification through close/lost.
- **REQ-SALES-002 Must:** Schedule, confirm, conduct and record viewing outcomes.
- **REQ-SALES-003 Must:** Record offers, validity, negotiation and decisions.
- **REQ-SALES-004 Must:** Hold/reserve units with expiry controls and deposit tracking.
- **REQ-SALES-005 Must:** Contract lifecycle linked to reservations, units and customers.

### 4.4 Finance
- **REQ-FIN-001 Must:** Receivables, payment status, references and reconciliation support.
- **REQ-FIN-002 Must:** Configurable commission calculation, approval and payment tracking.

### 4.5 Property management
- **REQ-PM-001 Must:** Owner management agreements and managed-unit portfolio.
- **REQ-PM-002 Must:** Tenancy lifecycle, tenant, rent, deposit and status.
- **REQ-PM-003 Must:** Maintenance ticket → vendor/work order → approval → completion workflow.
- **REQ-PM-004 Must:** Rent schedules, collections, partial payments and arrears.

### 4.6 Communications and tasks
- **REQ-COM-001 Must:** Central interaction history across supported channels.
- **REQ-COM-002 Must:** Follow-ups, reminders, ownership, due dates and escalation.

### 4.7 Documents
- **REQ-DOC-001 Must:** Secure metadata, versioning, expiry and access audit.

### 4.8 Marketing and reporting
- **REQ-MKT-001 Should:** Campaign attribution and lead-event tracking.
- **REQ-REP-001 Must:** Sales, pipeline, inventory, agents, maintenance and collections dashboards.

### 4.9 Security
- **REQ-SEC-001 Must:** RBAC and least privilege.
- **REQ-SEC-002 Must:** MFA for privileged users and configurable user groups.
- **REQ-SEC-003 Must:** Tamper-evident audit trail for sensitive actions.
- **REQ-SEC-004 Must:** Encryption, secrets management, retention and secure deletion controls.

### 4.10 Integrations
- **REQ-INT-001 Must:** Versioned REST API, webhooks, authentication and rate limiting.
- **REQ-INT-002 Must:** WhatsApp Business/provider integration where API access permits.
- **REQ-INT-003 Should:** Email/SMS transactional and customer messaging.
- **REQ-INT-004 Should:** CTI/click-to-call/call history where supported.
- **REQ-INT-005 Should:** Property portal feed/API adapters.
- **REQ-INT-006 Should:** ERP/accounting invoices, receipts, reconciliation and handoff.
- **REQ-INT-007 Must:** Applicable Saudi real-estate/tax regulatory workflows; exact interfaces must be validated against current licenses and platform APIs before implementation.

### 4.11 Mobile, operations and AI
- **REQ-MOB-001 Must:** Agent mobile workflows for leads, units, viewings and tasks.
- **REQ-OPS-001 Must:** Automated backup, restore testing, RPO/RTO and DR exercises.
- **REQ-OPS-002 Should:** Central logs, metrics, alerts and integration-health monitoring.
- **REQ-AI-001 Could:** Arabic/English message-to-structured customer requirement extraction.
- **REQ-AI-002 Could:** Explainable property matching using explicit customer criteria.
- **REQ-AI-003 Could:** Conversation/viewing/opportunity summaries with human review.

## 5. Non-functional requirements
| ID | Requirement |
|---|---|
| NFR-01 | Availability target ≥99.9% monthly excluding agreed maintenance |
| NFR-02 | Typical CRM screen/API target ≤2 seconds at normal load |
| NFR-03 | Scale branches, users, units and communications without redesign |
| NFR-04 | Secure SDLC, vulnerability management and periodic penetration testing |
| NFR-05 | Data minimization, retention, access control and applicable Saudi privacy obligations |
| NFR-06 | Arabic RTL + English LTR UI and customer-facing content |
| NFR-07 | Sensitive actions traceable to user/time/source |
| NFR-08 | Encrypted backups and periodic restore tests |
| NFR-09 | Documented RPO/RTO and periodic recovery exercises |
| NFR-10 | Versioned APIs, authentication, rate limiting and documentation |
| NFR-11 | WCAG-oriented usability where applicable |
| NFR-12 | Central logs, metrics and alerting |

## 6. Main modules
1. Organization & Administration
2. Reference Data
3. CRM / Customer 360
4. Lead Management & SLA
5. Property Inventory
6. Listings & Portal Publishing
7. Sales Pipeline
8. Viewings / Offers / Reservations / Contracts
9. Payments & Commissions
10. Property Management
11. Tenancy & Rent Collection
12. Maintenance & Vendors
13. Communications & Tasks
14. Documents
15. Marketing
16. Reporting & Dashboards
17. Security / Audit / Login Events
18. Integrations
19. Mobile Agent Workspace
20. Optional AI assistance

## 7. Core workflows
- **WF-01 Lead-to-Opportunity:** Capture → deduplicate → assign → SLA → qualify → opportunity.
- **WF-02 Property Matching:** Criteria → inventory search → shortlist → viewing.
- **WF-03 Viewing:** Schedule → confirm → conduct → outcome → follow-up.
- **WF-04 Offer-to-Contract:** Offer → negotiation → acceptance → reservation → contract → payment.
- **WF-05 Reservation:** Available → reserve → expiry control → convert or release.
- **WF-06 Rental Management:** Owner agreement → managed unit → tenant → tenancy → collection.
- **WF-07 Maintenance:** Ticket → triage → vendor/work order → approval → completion → close.
- **WF-08 Commission:** Closed contract → calculation → approval → payable → paid.
- **WF-09 Marketing Attribution:** Campaign → lead event → lead → opportunity → contract/revenue.
- **WF-10 Document Lifecycle:** Upload → classify → version → access → expiry → archive.

## 8. Validation rules
### Database-enforced baseline
- Lead budget minimum must not exceed maximum.
- Lead bedrooms minimum cannot be negative.
- Unit area must be positive when supplied.
- Unit asking/rent prices cannot be negative.
- Payment due/paid amounts must be non-negative and paid ≤ due.
- Rent collection due/paid amounts must be non-negative and paid ≤ due.
- Reservation expiry cannot precede reservation time.
- Viewing end cannot precede viewing start.
- Organization codes, role codes, reference codes and defined business numbers must respect approved unique constraints.

### Application validation
- Required fields are enforced before submission.
- Status transitions must follow the configured workflow/state machine.
- Users can operate only within their organization/branch/data scope unless explicitly authorized.
- Reservation and listing actions must re-check current unit availability transactionally.
- Expired documents must trigger warnings/notifications where expiry is required.
- Duplicate lead detection must use configurable matching rules rather than one fixed identifier.

## 9. Authentication and authorization
Authentication is an application/infrastructure concern; the approved 47-table database stores users, roles, permissions and login/audit events but does not store password hashes or MFA secrets.

Authorization must implement RBAC, least privilege, organization/branch scope, privileged MFA, session/token controls and deny-by-default behavior.

## 10. Error handling
All API errors must use a stable machine-readable error code, HTTP status, human-readable message, correlation/request ID and optional field-level validation details. Internal stack traces and secrets must never be exposed to clients.

## 11. Audit logging
Sensitive create/update/delete, authentication, authorization, document access, configuration, approval and integration actions must generate an audit event with actor, organization, entity, action, timestamp, source IP/user-agent where available, and before/after values where appropriate.

## 12. Notifications
Notification orchestration must support in-app/task notifications and external channels where configured: WhatsApp, email and SMS. SLA breaches, task due/overdue events, viewing reminders, reservation expiry, document expiry, payment/collection events and integration failures are primary notification triggers.

## 13. File/document management
The database stores document metadata and `storage_uri`; binary content belongs in secure object/file storage. Files require access control, encryption, malware scanning where applicable, versioning, hash integrity, retention/secure deletion policy and access logging.

## 14. Reporting requirements
Minimum dashboards: executive KPIs, lead funnel/SLA, pipeline by stage/agent/branch, inventory availability/pricing, listings, viewings/offers/reservations, sales/contract/payment status, commissions, managed portfolio, tenancy/occupancy, maintenance SLA/vendor performance, rent collections/arrears, campaign attribution, communications/task workload, security/audit and integration health.

## 15. Testing requirements
- Unit tests for domain rules and services.
- API integration/contract tests.
- Database migration and constraint tests.
- Workflow/state-transition tests.
- RBAC/authorization and MFA tests.
- File upload/access/expiry/hash tests.
- Integration tests with mocked external providers.
- End-to-end tests for all Must workflows.
- Performance/load tests against NFR-01/NFR-02 targets.
- Security testing: SAST, dependency scanning, DAST and periodic penetration testing.
- Backup restore and DR exercise tests.
- Arabic/English, RTL/LTR and accessibility tests.
- UAT with scripted acceptance for every Must requirement.
