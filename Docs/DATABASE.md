# DATABASE.md

# Real Estate CRM — Database Specification
**Version:** 1.0  
**Database:** PostgreSQL 15+  
**Approved baseline:** 47 tables

## 1. Database principles
- UUID primary keys.
- Normalized relational core.
- `numeric(18,2)` for money.
- `numeric(12,2)` for area.
- `timestamptz` for operational timestamps.
- External binary files are stored outside PostgreSQL; DB stores `storage_uri` and hash metadata.
- Sensitive national identity is represented as `national_id_hash` in the approved model.
- Business-generated numbers are unique where defined.
- Statuses remain varchar in the approved baseline; application/domain services own the allowed state transitions.

## 2. Table inventory
### Organization
`organizations`, `branches`, `users`, `roles`, `user_roles`

### Reference
`cities`, `property_types`, `lead_sources`, `loss_reasons`, `activity_types`, `document_types`

### CRM
`customers`, `leads`, `lead_notes`

### Property Inventory
`projects`, `buildings`, `units`, `unit_status_history`, `listings`, `property_media`

### Sales
`opportunities`, `opportunity_units`, `viewings`, `offers`, `reservations`, `contracts`, `payments`, `commissions`

### Property Management
`management_contracts`, `managed_units`, `tenancies`, `maintenance_tickets`, `vendors`, `maintenance_work_orders`, `rent_collections`

### Communications
`activities`, `communications`, `tasks`

### Documents
`documents`, `document_access_log`

### Marketing
`campaigns`, `campaign_leads`, `lead_events`

### Security
`permissions`, `role_permissions`, `audit_logs`, `login_events`

## 3. Core relationships
```text
organizations 1:N branches
organizations 1:N users
users M:N roles via user_roles

customers 1:N leads
leads 1:N opportunities

projects 1:N buildings
buildings 1:N units
units 1:N listings
units 1:N unit_status_history

opportunities M:N units via opportunity_units
opportunities 1:N viewings
opportunities 1:N offers
opportunities 1:N reservations
reservations 1:0..1 contracts
contracts 1:N payments
contracts 1:N commissions

customers 1:N management_contracts
management_contracts M:N units via managed_units
units 1:N tenancies
units 1:N maintenance_tickets
maintenance_tickets 1:N maintenance_work_orders

campaigns M:N leads via campaign_leads
leads 1:N lead_events

documents 1:N document_access_log
roles M:N permissions via role_permissions
```

## 4. Key entity responsibilities
| Entity | Responsibility |
|---|---|
| organizations | Tenant/company boundary and organization settings |
| branches | Branch structure and branch-level ownership |
| users | Operational users and managers |
| roles/user_roles | RBAC role assignment |
| cities/property_types | Reference data for geographic and property classification |
| customers | Customer 360 identity and contact profile |
| leads | Inquiries, qualification, assignment and requirements |
| projects/buildings/units | Property hierarchy and inventory |
| listings | Portal/listing publication records |
| opportunities | Sales pipeline |
| viewings/offers/reservations/contracts | Sales progression |
| payments/commissions | Financial transaction tracking |
| management_contracts/managed_units | Owner portfolio management |
| tenancies | Leasing lifecycle |
| maintenance_tickets/work_orders/vendors | Maintenance workflow |
| rent_collections | Rental receivables/collections |
| activities/communications/tasks | Interaction and follow-up history |
| documents/access log | Secure document metadata and audit |
| campaigns/campaign_leads/lead_events | Marketing attribution |
| audit_logs/login_events | Security and operational traceability |

## 5. Approved constraints
The baseline includes unique constraints for organization codes, organization tax number, branch code within organization, user employee/email within organization, role code within organization, reference codes, building code within project, external listing ID, media file hash, reservation number, contract number, payment reference, management contract number, tenancy contract number, vendor tax number, communication external message ID, document file hash and permission code.

Database CHECK constraints include:
- `leads`: budget_min ≤ budget_max when both exist.
- `leads`: bedrooms_min ≥ 0.
- `units`: area_sqm > 0 when supplied.
- `units`: asking_price and rent_price ≥ 0 when supplied.
- `payments`: amount_due ≥ 0, amount_paid ≥ 0 and amount_paid ≤ amount_due.
- `rent_collections`: amount_due ≥ 0, amount_paid ≥ 0 and amount_paid ≤ amount_due.
- `reservations`: expires_at ≥ reserved_at when expiry exists.
- `viewings`: scheduled_end ≥ scheduled_start when end exists.

## 6. Indexing
The approved baseline includes indexes for organization/branch access, lead status/assignment/source/SLA, opportunity stage/agent, unit building/status/owner/type, listing status, viewing schedules, reservation status, contract status, payment status, commission status, tenancy status, maintenance status, collection due/status, communications by customer/time, tasks by assignee/due/status, documents by customer/contract, campaign attribution, lead events and audit/login timelines.

## 7. Transactional integrity rules
- Reservation availability must be checked inside a transaction and revalidated at commit time.
- Contract creation must be idempotent with respect to its business number and reservation conversion workflow.
- Payment posting must preserve amount constraints and reconciliation references.
- Status history should be written whenever a tracked unit status changes.
- Audit records must be emitted for sensitive mutations even when the underlying table does not contain a direct audit FK.

## 8. Document storage model
`documents.storage_uri` points to external secure storage. `file_hash` provides integrity/deduplication support. `version_no` tracks document versions. `document_access_log` records access actions. The application controls authorization and generates short-lived access links.

## 9. Known baseline boundaries — not silently changed
The approved 47-table schema intentionally does not itself implement password/MFA secret storage, notification queues/templates, integration credentials, API keys, rate-limit state, workflow configuration, or reporting data marts. These are application/infrastructure concerns unless a future approved schema change adds them.

The baseline also has global uniqueness for several external/file identifiers; changing their scope would be a schema/business-rule change and requires explicit approval.

## 10. Migration order
1. `001_extensions.sql`
2. `002_organization_reference.sql`
3. `003_crm.sql`
4. `004_property_inventory.sql`
5. `005_sales.sql`
6. `006_property_management.sql`
7. `007_communications_documents_marketing.sql`
8. `008_security.sql`
9. `009_indexes_integrity.sql`

The optional schema-completeness extension is not part of the approved 47-table baseline and must not be applied automatically.
