# Technical & Saudi Real Estate Domain Glossary

> **Audience**: All project stakeholders, beginner developers, real estate brokers, and system maintainers.  
> **Scope**: Standardized definitions, acronyms, and operational terminology used across the RECRM codebase, architecture, and business documentation.

---

## 1. Technical & Software Engineering Terms

### Asynchronous I/O (`async` / `await`)
A programming pattern in Python where input/output operations (such as database queries or network requests) do not block the thread execution. While waiting for PostgreSQL to return data, Python serves other concurrent user requests.

### `asyncpg`
A high-performance, pure-Python and Cython driver for PostgreSQL. Unlike traditional ORMs, `asyncpg` connects directly over PostgreSQL's binary wire protocol and executes raw parameterized SQL queries with zero object hydration overhead.

### Concurrency Lock (`SELECT ... FOR UPDATE`)
An exclusive row-level database lock acquired inside a transaction. In RECRM, when reserving a unit, the database locks the specific row in the `units` table until the transaction completes, preventing two brokers from booking the same property at the same instant (race condition).

### Data Scoping
A multi-tier data authorization model that restricts which records a user can read or modify based on their assigned role and organizational tier. The 4 scoping levels in RECRM are:
- `GLOBAL`: Organization-wide visibility across all branches.
- `BRANCH`: Scoped exclusively to the user's assigned physical branch.
- `TEAM`: Scoped to a specific operational team or sales directorate.
- `OWN`: Frontline agent isolation; users only see records assigned directly to them.

### Error Envelope (`ErrorEnvelope`)
A standardized JSON response format returned for all HTTP 4xx and 5xx errors, containing a top-level `error` object with machine-readable `code`, human-readable `message`, unique `request_id`, and field-specific validation errors.

### FastAPI
A modern, high-performance web framework for building APIs with Python 3.8+ based on standard Python type hints, Starlette ASGI, and Pydantic validation.

### PostgreSQL Sequence (`seq_{table}_id`)
A dedicated database object that generates sequential, non-colliding integers. RECRM prefixes sequence values to create clean, human-readable alphanumeric identifiers (e.g., `cust-101`, `lead-205`, `res-15`).

### Pydantic (V2)
A data validation and serialization library for Python that enforces strict type annotations. It parses incoming request payloads, validates data formats (such as Saudi phone numbers and positive prices), and serializes response data.

### Role-Based Access Control (RBAC)
A security model that assigns permissions (such as `LEAD_READ`, `SALES_WRITE`, `PAYMENT_APPROVE`) to predefined roles (`SYS_ADMIN`, `SALES_AGENT`, `ACCOUNTANT`), which are then granted to individual staff users.

### State Machine
A mathematical and software design pattern where an entity (such as a Lead, Deal, or Task) can exist in only one specific state at a time, and transitions between states are governed by strict business rules and SOP checklist validations.

### Starlette & Uvicorn
- **Uvicorn**: A lightning-fast ASGI (Asynchronous Server Gateway Interface) web server implementation for Python.
- **Starlette**: The underlying lightweight toolkit that powers FastAPI's routing, request lifecycle, static file mounting, and middleware.

---

## 2. Saudi Real Estate & Regulatory Terms

### Araboun / العربون (Earnest Money Deposit)
A preliminary monetary deposit paid by a prospective buyer or tenant to demonstrate serious intent and lock a property for a temporary period (typically 48 hours in RECRM). If the buyer defaults without valid justification, the deposit is handled according to Saudi contract law.

### Cap Rate / معدل الرسملة (Capitalization Rate)
A foundational commercial real estate investment metric calculated as:
$$\text{Cap Rate (\%)} = \left(\frac{\text{Net Operating Income (NOI)}}{\text{Current Property Purchase Price}}\right) \times 100$$
It indicates the unleveraged rate of return an investor can expect from a property.

### Customer 360 / ملف العميل 360
A unified client profile screen aggregating the complete lifecycle of a client: National ID/CR, AML risk tier, active deals, contracts, viewing appointments, payment receipts, and communication logs.

### Ejar / منصة إيجار
The official electronic rental network managed by the Saudi Ministry of Municipal and Rural Affairs and Housing. Under Saudi regulations, all residential and commercial tenancy contracts must be registered and authenticated on the Ejar platform to have legal standing in Saudi courts.

### FAL License / رخصة فال العقارية
The mandatory professional broker license issued by REGA. All real estate brokerage offices and individual agents in Saudi Arabia must hold a valid FAL license to market properties, conduct viewings, or collect commissions.

### Gross Rental Yield / العائد الإيجاري الإجمالي
The percentage return on property value from gross rental income before operating expenses:
$$\text{Gross Yield (\%)} = \left(\frac{\text{Annual Gross Rental Income}}{\text{Property Purchase Price}}\right) \times 100$$

### Net Operating Income (NOI) / صافي دخل التشغيل
Total gross revenue generated by an investment property minus all necessary operating expenses (OPEX):
$$\text{NOI} = \text{Gross Rental Income} - \text{Operating Expenses}$$
Operating expenses include facility maintenance, elevator servicing, municipal fees, building insurance, and property management fees.

### Net Rental Yield / العائد الإيجاري الصافي
The true operational return on investment factoring in all maintenance and management expenses:
$$\text{Net Yield (\%)} = \left(\frac{\text{Net Operating Income (NOI)}}{\text{Property Purchase Price}}\right) \times 100$$

### REGA / الهيئة العامة للعقار (Real Estate General Authority)
The central regulatory authority responsible for organizing, licensing, and supervising real estate activities, marketing compliance, and broker licensing in the Kingdom of Saudi Arabia.

### RETT / ضريبة التصرفات العقارية (Real Estate Transaction Tax)
A mandatory government tax of **5%** imposed on the total value of any real estate sale or transfer in Saudi Arabia, administered by ZATCA. It is distinct from Value Added Tax (VAT) and is exempt for first-time Saudi homebuyers up to 1,000,000 SAR.

### Standard Operating Procedure (SOP) / إجراءات العمل القياسية
A codified sequence of operational steps and mandatory verification checklists required before completing a task (e.g. confirming title deed authenticity, verifying National ID, obtaining signed brokerage contracts).

### Statutory Brokerage Fee / سعي الوساطة العقارية
Under REGA regulations, the maximum commission a brokerage agency may charge for real estate transactions is **capped at 2.5%** of the total transaction value (unless expressly agreed in writing otherwise by the parties).

### Sukuk / الصك العقاري (Electronic Title Deed)
The official electronic title deed issued by the Saudi Ministry of Justice confirming legal ownership of a parcel of land, building, or partitioned residential/commercial unit.

### Taqeem / الهيئة السعودية للمقيمين المعتمدين (Saudi Authority for Accredited Valuers)
The government authority that regulates and licenses certified real estate appraisers who provide accredited market valuation reports for financing and investment due diligence.

### Value Added Tax (VAT) / ضريبة القيمة المضافة
A **15% tax** administered by ZATCA that applies to commercial brokerage services, marketing services, and property management administration fees in Saudi Arabia.

### Wafi / وافي (Off-Plan Sales & Rent Licensing)
The official Saudi program that licenses developers to sell or rent real estate units before construction is completed (off-plan sales).

### ZATCA / هيئة الزكاة والضريبة والجمارك (Zakat, Tax and Customs Authority)
The Saudi government authority responsible for the collection of Zakat, customs duties, RETT, and VAT, as well as enforcing the national Electronic Invoicing (Fatoora) standards (Phase 1 & Phase 2).

