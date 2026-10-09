# API.md

# Real Estate CRM — REST API Specification
**Version:** 1.0  
**Style:** Versioned REST/JSON over HTTPS  
**Status:** Application-level contract derived from approved requirements; endpoint naming is implementation guidance, not a database change.

## 1. API principles
- Base path: `/api/v1`.
- JSON request/response unless file upload/download requires multipart or signed object-storage URLs.
- HTTPS only.
- OAuth 2.0/OIDC or enterprise SSO-compatible authentication is preferred; exact identity provider is implementation-dependent.
- Access token validation plus RBAC/scope authorization.
- Correlation/request ID on every request.
- Pagination for collection endpoints.
- Stable resource IDs using UUIDs.
- Idempotency keys for operations that can create financial or reservation side effects.
- Rate limiting by user/client/IP according to endpoint sensitivity.
- API documentation via OpenAPI 3.x.

## 2. Common response model
### Success
```json
{
  "data": {},
  "meta": {"request_id": "..."}
}
```

### Collection
```json
{
  "data": [],
  "meta": {
    "request_id": "...",
    "page": 1,
    "page_size": 50,
    "total": 0
  }
}
```

### Error
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "request_id": "...",
    "fields": {
      "budget_min": ["must be less than or equal to budget_max"]
    }
  }
}
```

## 3. Core resources
### Authentication/session
- `GET /api/v1/me`
- `POST /api/v1/auth/logout` when the selected identity architecture requires application logout.
- Authentication itself may be handled by the IdP rather than CRM APIs.

### Organizations/administration
- `GET /organizations`
- `GET /organizations/{id}`
- `GET/POST/PATCH /branches`
- `GET/POST/PATCH /users`
- `GET/POST/PATCH /roles`
- `POST/DELETE /users/{id}/roles/{roleId}`
- `GET/POST/PATCH /permissions`
- `POST/DELETE /roles/{id}/permissions/{permissionId}`

### Reference data
- `GET /cities`
- `GET /property-types`
- `GET /lead-sources`
- `GET /loss-reasons`
- `GET /activity-types`
- `GET /document-types`

### Customers and CRM
- `GET/POST /customers`
- `GET/PATCH /customers/{id}`
- `GET /customers/{id}/360`
- `GET/POST /leads`
- `GET/PATCH /leads/{id}`
- `POST /leads/{id}/qualify`
- `POST /leads/{id}/assign`
- `POST /leads/{id}/notes`
- `GET /leads/{id}/notes`
- `POST /leads/{id}/deduplicate/check`

### Property inventory
- `GET/POST/PATCH /projects`
- `GET/POST/PATCH /projects/{id}/buildings`
- `GET/POST/PATCH /units`
- `GET /units/search`
- `POST /units/{id}/status`
- `GET /units/{id}/status-history`
- `GET/POST/PATCH /units/{id}/listings`
- `POST /listings/{id}/publish`
- `POST /listings/{id}/pause`
- `POST /listings/{id}/expire`
- `POST /units/{id}/media`

### Sales
- `GET/POST/PATCH /opportunities`
- `POST /opportunities/{id}/units`
- `DELETE /opportunities/{id}/units/{unitId}`
- `GET/POST /viewings`
- `PATCH /viewings/{id}`
- `GET/POST /offers`
- `PATCH /offers/{id}`
- `GET/POST /reservations`
- `POST /reservations/{id}/release`
- `POST /reservations/{id}/convert-to-contract`
- `GET/POST/PATCH /contracts`
- `GET/POST /contracts/{id}/payments`
- `GET/POST /contracts/{id}/commissions`

### Property management
- `GET/POST/PATCH /management-contracts`
- `POST/DELETE /management-contracts/{id}/units/{unitId}`
- `GET/POST/PATCH /tenancies`
- `GET/POST /maintenance-tickets`
- `PATCH /maintenance-tickets/{id}`
- `GET/POST /maintenance-tickets/{id}/work-orders`
- `GET/POST/PATCH /vendors`
- `GET/POST /tenancies/{id}/rent-collections`

### Communications/tasks
- `GET/POST /activities`
- `GET/POST /communications`
- `GET/POST/PATCH /tasks`
- `POST /tasks/{id}/complete`

### Documents
- `GET/POST /documents`
- `POST /documents/upload-url`
- `GET /documents/{id}`
- `POST /documents/{id}/versions`
- `POST /documents/{id}/access-url`
- `GET /documents/{id}/access-log`
- `POST /documents/{id}/archive`

### Marketing
- `GET/POST/PATCH /campaigns`
- `POST /campaigns/{id}/leads/{leadId}`
- `GET/POST /leads/{id}/events`

### Reporting
- `GET /reports/executive`
- `GET /reports/leads`
- `GET /reports/pipeline`
- `GET /reports/inventory`
- `GET /reports/sales`
- `GET /reports/maintenance`
- `GET /reports/collections`
- `GET /reports/commissions`
- `GET /reports/marketing`
- `GET /reports/security`
- `GET /reports/integrations/health`

## 4. Webhooks
Expose versioned webhook endpoints where external providers require inbound events. Every webhook must validate provider signatures, prevent replay, store a correlation/idempotency key, acknowledge quickly and process asynchronously when practical.

Example categories:
- WhatsApp message/delivery events.
- Email/SMS delivery events.
- Portal lead/listing events.
- Payment/accounting events.
- Identity events where supported.

## 5. Validation
API validation must enforce both schema constraints and domain rules. Examples: required fields, monetary non-negativity, budget ordering, valid dates, reservation availability, role scope, unique business numbers and valid state transitions.

## 6. Error mapping
| HTTP | Use |
|---|---|
| 400 | Malformed request |
| 401 | Missing/invalid authentication |
| 403 | Authenticated but unauthorized |
| 404 | Resource not found or not visible in caller scope |
| 409 | State conflict, duplicate unique value, reservation conflict or idempotency conflict |
| 422 | Semantic validation failure |
| 429 | Rate limit exceeded |
| 500 | Unexpected server error |
| 502/503/504 | External dependency unavailable/timeout |

## 7. Security requirements
- No secrets in request logs.
- No sensitive personal data in error messages.
- Enforce object-level authorization on every resource.
- Validate upload MIME type/size and content as appropriate.
- Signed/short-lived document URLs.
- CSRF protection where cookie-based sessions are used.
- CORS restricted to approved origins.
- Security headers at the edge/application layer.
- Audit all privileged and sensitive mutations.

## 8. Notifications API behavior
Notification generation is event-driven rather than a direct client-side responsibility. Events such as lead SLA breach, viewing reminder, reservation expiry, document expiry, payment/collection change and integration failure produce notification jobs. Delivery status is recorded through the communications/integration layer.

## 9. Reporting API behavior
Reports must accept controlled filters such as organization, branch, date range, agent, stage/status, city, property type and campaign. Large exports should be asynchronous and protected by authorization and rate limits.

## 10. API testing
- OpenAPI schema validation.
- Contract tests.
- Authentication/authorization tests.
- Negative validation tests.
- Idempotency/retry tests.
- Rate-limit tests.
- Integration webhook signature/replay tests.
- Performance tests against NFR targets.
