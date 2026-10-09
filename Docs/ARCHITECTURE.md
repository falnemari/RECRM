# ARCHITECTURE.md

# Real Estate CRM — Solution Architecture
**Version:** 1.0  
**Baseline:** approved requirements + approved 47-table PostgreSQL model

## 1. Architecture principles
- API-first and integration-ready.
- Modular business domains with clear service boundaries.
- PostgreSQL is the system of record for transactional CRM data.
- Object storage is the system of record for binary documents/media.
- Authentication is delegated to an enterprise-capable identity provider where available; application authorization remains RBAC-based.
- No direct browser access to PostgreSQL.
- All sensitive operations are auditable.
- Arabic/English and RTL/LTR are first-class requirements.
- External integrations are isolated behind adapters/connectors.
- Approved business requirements and the 47-table baseline are versioned; changes require explicit change control.

## 2. Logical architecture
```text
Web UI / Mobile Agent UI
          |
      HTTPS / TLS
          |
   API Gateway / BFF
          |
  Authentication / Token validation
          |
  Application / Domain Services
  |      |       |       |       |
 CRM   Sales   Property   PM    Finance
  |      |       |       |       |
 Communications / Documents / Marketing / Reporting
          |
     PostgreSQL 15+
          |
 Object Storage   Message/Job Queue   Observability
          |
 External Integration Adapters
  |       |       |       |       |       |
WhatsApp Email/SMS CTI Portals ERP Saudi/SSO Maps
```

## 3. Frontend
The frontend should be a responsive bilingual web application with a mobile-first agent experience. It consumes versioned REST APIs and never connects directly to the database.

Core frontend areas: dashboard, leads, customers, properties, sales pipeline, viewings, offers, reservations, contracts, payments, commissions, property management, tenancies, maintenance, collections, communications, tasks, documents, campaigns, reports and administration.

## 4. Backend modules/services
### Identity and access
- Authentication integration.
- Session/token validation.
- MFA policy enforcement for privileged/configured groups.
- RBAC and scope evaluation.

### Organization service
Organizations, branches, users, roles and user-role assignments.

### Reference service
Cities, property types, lead sources, loss reasons, activity types and document types.

### CRM service
Customers, leads, deduplication, assignment, SLA and lead notes.

### Property service
Projects, buildings, units, status history, listings and media.

### Sales service
Opportunities, opportunity-unit matching, viewings, offers, reservations, contracts, payments and commissions.

### Property management service
Management contracts, managed units, tenancies, maintenance tickets, vendors, work orders and rent collections.

### Communications service
Activities, communications, tasks, templates, delivery state and notification orchestration.

### Document service
Metadata, versioning, secure storage integration, access control, expiry and access audit.

### Marketing service
Campaigns, campaign-lead attribution and lead events.

### Reporting service
Read-optimized queries/materialized reporting views as required; dashboards must not compromise OLTP transactions.

### Audit service
Central audit event generation, tamper-evident storage strategy and security-event correlation.

## 5. Integration architecture
Each external system is accessed through an adapter with:
- credential/secret isolation;
- timeout and retry policy;
- idempotency where supported;
- rate limiting;
- dead-letter/reconciliation handling;
- inbound/outbound correlation IDs;
- monitoring and health status;
- audit logging for sensitive exchanges.

Required/target integrations: website/landing pages, WhatsApp Business/API, email, SMS, CTI, property portals, accounting/ERP, identity/SSO, object storage, maps/geocoding, applicable Saudi platforms and optional BI.

## 6. Data architecture
PostgreSQL 15+ is the approved relational baseline. UUIDs are primary keys. Money uses `numeric(18,2)`, area uses `numeric(12,2)`, and timestamps use `timestamptz` in the approved DDL.

The 47 approved tables remain the transactional core. No application service may bypass domain authorization by writing arbitrary SQL from the client.

## 7. Security architecture
- TLS for all network communication.
- Encryption at rest for database, backups and object storage.
- Secrets stored in a secrets manager, never source code.
- MFA for privileged/configured users.
- RBAC with least privilege and deny-by-default.
- Organization/branch data scoping.
- Secure document URLs, preferably short-lived signed URLs.
- Malware/content validation for uploads where applicable.
- Central audit logging and security monitoring.
- Rate limiting and abuse protection.
- Secure SDLC and vulnerability management.

## 8. Availability, backup and DR
Target availability is ≥99.9% monthly excluding agreed maintenance. Backups must be encrypted, monitored and periodically restored in a test environment. RPO/RTO values must be agreed in the implementation plan and validated through recovery exercises.

## 9. Observability
Collect structured application logs, metrics, traces where practical, audit events, job status, API latency/error rates, integration health, queue depth, database health, storage errors and security events. Alerts must be actionable and routed to the responsible team.

## 10. Deployment model
The solution may be deployed on approved cloud, private infrastructure or hybrid infrastructure. Environment separation is required for development, test/UAT and production. Production secrets and data must not be copied into development without approved sanitization.

## 11. Architecture decision boundaries
The approved specification does not mandate a particular frontend framework, backend language, API gateway, message broker, cloud provider or identity vendor. Those are implementation decisions subject to performance, security, maintainability, Saudi hosting/compliance requirements and procurement constraints.
