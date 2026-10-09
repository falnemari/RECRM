# UI.md

# Real Estate CRM — UI/UX Specification
**Version:** 1.0  
**Audience:** UX/UI, frontend developers, QA and business stakeholders

## 1. UI principles
- Arabic and English are equal first-class languages.
- RTL for Arabic and LTR for English.
- Responsive desktop/tablet/mobile layouts.
- Role-aware navigation and actions.
- Clear status, SLA, ownership and next-action indicators.
- Avoid destructive actions without confirmation.
- Consistent filters, search, pagination, sorting and saved views.
- Accessibility-oriented controls and keyboard navigation where practical.
- Dates/times/currency respect organization settings and locale.

## 2. Global shell
### Header
- Organization/branch context.
- Global search.
- Notifications.
- Language switcher.
- User profile/security menu.

### Navigation
Dashboard, CRM, Leads, Customers, Properties, Sales, Property Management, Communications, Documents, Marketing, Reports, Administration.
Navigation is filtered by role/permission.

## 3. Frontend pages
| Area | Pages |
|---|---|
| Dashboard | Executive dashboard, branch dashboard, agent dashboard, property-management dashboard |
| Leads | Lead list, lead detail, lead creation/import, SLA queue, duplicate review |
| Customers | Customer list, Customer 360, create/edit customer, interaction timeline |
| Properties | Projects, buildings, units, unit detail, inventory search, status history |
| Listings | Listing list, listing editor, publishing status, portal errors/history |
| Sales | Pipeline board, opportunity list/detail, matching results, viewings, offers, reservations, contracts |
| Finance | Payment schedule/list, payment detail, commissions, reconciliation work queue |
| Property Management | Management contracts, managed portfolio, tenancies, collections, arrears |
| Maintenance | Ticket queue, ticket detail, vendor list, work orders, approval/completion workflow |
| Communications | Unified interaction timeline, message composer, channel status |
| Tasks | My tasks, team tasks, overdue/SLA queue |
| Documents | Document list, upload, metadata/version panel, expiry queue, access log |
| Marketing | Campaign list/detail, attribution, lead events |
| Reports | Executive, sales, pipeline, inventory, maintenance, collections, commissions, marketing, security |
| Administration | Organization, branches, users, roles, permissions, reference data, integrations, audit, login events |

## 4. Lead detail page
Must show:
- Customer identity/contact information.
- Lead source, status, priority and inquiry type.
- Assigned user and branch.
- Budget range and property requirements.
- SLA due/actual contact time.
- Notes.
- Related opportunities, viewings, offers and tasks.
- Communications timeline.
- Campaign attribution/events.
- Documents where applicable.

Primary actions: assign, qualify, create opportunity, add note, schedule task, communicate, mark outcome.

## 5. Customer 360
Tabs/sections:
1. Profile.
2. Leads.
3. Opportunities.
4. Viewings/offers/reservations/contracts.
5. Tenancies/management relationships.
6. Payments/collections where authorized.
7. Communications.
8. Tasks/activities.
9. Documents.
10. Audit-relevant history for authorized users.

## 6. Property/unit UI
Unit detail must expose project/building context, property type, floor, area, bedrooms, bathrooms, parking, orientation, asking/rent price, owner, assigned agent, current status, status history, listings, media, sales relationships and management/tenancy relationships where authorized.

Inventory search must support city/property type/status/price/area/bedrooms and other explicit customer criteria.

## 7. Sales pipeline
A configurable board/list view with stages such as qualification, opportunity, negotiation, reservation, contract/closed and lost, subject to the final approved business workflow. Cards show customer, unit, value, assigned agent, expected close date and SLA/next action.

## 8. Reservation and contract UX
Reservation action must display current availability, expiry, deposit and conflict warnings. Contract conversion must show the reservation and unit/customer context and require confirmation. Financial actions must show amounts, references and current balance/status.

## 9. Property management UX
### Management contract
Owner, contract number, dates, status and managed units.

### Tenancy
Unit, tenant, lease number, dates, rent, frequency, deposit and status.

### Maintenance
Ticket priority/category/status, description, reported-by, assigned coordinator, due date, vendor/work order, quoted/approved amount and completion state.

### Collections
Due date, amount due, amount paid, balance, status, paid date and arrears filters.

## 10. Documents UX
- Drag/drop or file picker.
- Document type classification.
- Customer/unit/contract association.
- Version display.
- Issue/expiry dates.
- Expiry warnings.
- Authorized preview/download using short-lived access URLs.
- Access history for authorized users.
- Archive action with confirmation.

## 11. Notifications UX
Notification center should show unread/read state, severity, source and direct navigation to the affected entity. Priority alerts include SLA breach, overdue task, viewing reminder, reservation expiry, document expiry, payment/collection issue and integration failure.

## 12. Reporting UX
Reports should provide:
- date filters;
- organization/branch filters;
- agent/team filters;
- property/status filters;
- KPI cards;
- charts/tables;
- drill-down to source records;
- export subject to permission;
- clear “as of” timestamp.

## 13. Security UX
- MFA enrollment/challenge through the selected identity system.
- Session/security activity where supported.
- Role/permission administration restricted to authorized administrators.
- Audit and login event screens read-only for auditors unless explicit elevated permission exists.
- Sensitive actions require confirmation and may require step-up authentication.

## 14. Validation and errors
Inline validation should identify the exact field and corrective action. Server validation remains authoritative. Concurrency conflicts such as reservation status changes must be displayed as a current-state conflict rather than silently overwriting data.

## 15. Mobile agent experience
Prioritize:
- My leads.
- Lead/customer 360.
- Unit search.
- Viewings and calendar.
- Tasks.
- Quick communication.
- Directions/maps where integrated.
- Offer/reservation actions subject to permission.
- Offline behavior, if implemented, must define synchronization/conflict rules before production.

## 16. UI testing
- Component/unit tests.
- Role-based visibility tests.
- End-to-end critical workflows.
- Responsive/mobile tests.
- Arabic/English and RTL/LTR tests.
- Accessibility tests.
- Cross-browser support for approved browser matrix.
- Error/concurrency tests for reservations and financial workflows.
