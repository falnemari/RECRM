# How the Real Estate CRM should handle renting, buying, and investment

The key principle is that the CRM should not run every customer through the same workflow. It should identify the customer's purpose, create the correct business process, generate the appropriate tasks and activities, and change business statuses only when a defined condition has been met.

For example, a customer who wants to rent an apartment needs availability checks, viewing appointments, tenancy terms, and rental payments. A buyer needs property matching, offers, negotiation, reservation, and a purchase contract. An investor may need all of those services plus return-on-investment calculations, rental forecasts, expenses, and comparisons between multiple properties.

Your approved 47-table database already contains many of the core entities needed for these processes. We should build the business rules around the existing schema and treat any proposed database changes as a separate, explicitly approved decision.

## 1. First, distinguish the customer's purpose


## A. Renting

Typical objective: occupy a property for a period in return for rent.

- Match budget, location, bedrooms, and move-in date.
- Check unit availability and arrange viewings.
- Negotiate rent, deposit, and tenancy terms.
- Prepare and sign the tenancy agreement.
- Track rent due dates, payments, renewals, and maintenance. Main entities: `customers`, `leads`, `opportunities`, `units`, `viewings`, `management_contracts`, `tenancies`, `rent_collections`, `tasks`, `activities`, `communications`.

## B. Buying

Typical objective: purchase a property for personal use or another purpose.

- Qualify the buyer's budget and financing.
- Match properties and confirm their sale availability.
- Arrange viewings and record feedback.
- Manage offers, counteroffers, and negotiations.
- Process reservation, documentation, payment coordination, and contract completion. Main entities: `customers`, `leads`, `opportunities`, `opportunity_units`, `viewings`, `offers`, `reservations`, `contracts`, `payments`, `commissions`, `documents`.

## C. Investment

Typical objective: earn rental income, achieve capital appreciation, or combine both.

- Establish the investment budget, financing, time horizon, and risk tolerance.
- Compare candidate properties by expected net income and return.
- Estimate vacancy, maintenance, operating expenses, and financing costs.
- Manage acquisition and, where applicable, leasing and property management.
- Track actual performance against forecasts. Main entities: the buying entities plus `tenancies`, `rent_collections`, `maintenance_tickets`, `payments`, `managed_units`, and reporting logic.

Important: Investment is not always a separate transaction type. An investor might buy a unit, rent it out, and later sell it. The CRM should therefore distinguish the customer's purpose from the transaction being processed.

A customer may also have multiple opportunities simultaneously—for example, renting an apartment for their family while buying an investment property. Each opportunity should have its own workflow.

## 2. The business rules that control the workflow

Think of the CRM as a business rules engine. Every workflow should answer five questions:

1. Trigger: What happened?
2. Condition: Does the customer qualify for the next step?
3. Action: Which task, activity, communication, or record must be created?
4. Business effect: Which status or financial value may change?
5. Control: Who must approve it, and what happens if it is overdue or fails?

For example, creating a lead should not automatically mark it as qualified. It should create a first-contact task. Only after the employee records enough information to satisfy your qualification rules should the lead move to the qualified stage.

### Example: the lead-to-transaction decision

Customer / Lead Created

Capture source, contact details, budget and purpose

Determine Customer Purpose

Rent · Buy · Investment · Multiple purposes

Rent

Availability → Viewing → Tenancy

Buy

Matching → Offer → Sale

Invest

Compare returns → Acquire → Monitor

Verify Conditions Before Advancing

Eligibility · Availability · Approvals · Documents · Payments

A purpose can be recorded as a lead requirement, but the system should create a separate opportunity for each distinct transaction. If the approved `leads` table does not contain a suitable purpose field, first determine whether the current schema can represent the information elsewhere. Do not silently add a column or table; propose a schema change if necessary.

## 3. The equations that make the business work correctly

There are two kinds of equations:

- Business rules: determine what the system is allowed to do.
- Financial equations: calculate affordability, rental yield, investment returns, commissions, and performance.

Both are necessary.

### A. Customer qualification and property matching

Rule 1 — Budget validity

\\[ B\_{\min} \leq B\_{\max} \\]

If both values are supplied, the minimum budget cannot exceed the maximum budget. This is consistent with the existing database constraint.

Rule 2 — Property budget match

For a rental opportunity:

\\[ R\_{\text{property}} \leq B\_{\text{rent,max}} \\]

For a purchase opportunity:

\\[ P\_{\text{property}} \leq B\_{\text{purchase,max}} \\]

For an investment opportunity, the purchase price alone is not sufficient; expected returns and costs must also be considered.

Rule 3 — Property eligibility

A property should qualify only if all mandatory conditions are satisfied:

\\[ \text{Eligible} = \text{Available} \land \text{BudgetMatch} \land \text{LocationMatch} \land \text{RequirementsMatch} \\]

Here, \\(\land\\) means AND. If the customer requires three bedrooms, a property with two bedrooms fails that mandatory condition unless the customer explicitly relaxes it.

Rule 4 — Property matching score

After applying mandatory filters, rank the remaining properties:

\\[ S = \sum\_{i=1}^{n} w_i s_i \\]

Where:

- \\(s_i\\) is the match score for one factor, normalized from 0 to 100.
- \\(w_i\\) is the weight assigned to that factor.
- \\(\sum w_i = 1\\).

Example weights:

| Matching factor            | Weight |
| -------------------------- | ------ |
| Budget                     | 30%    |
| Location                   | 25%    |
| Property size and bedrooms | 20%    |
| Amenities                  | 10%    |
| Move-in or purchase timing | 15%    |
| Total                      | 100%   |

A score helps rank properties; it must not override mandatory conditions such as availability or legal eligibility.

### B. Rental calculations

For a rental property, the CRM should calculate the following when the relevant inputs are available.

1\. Annual gross rent

\\[ G = R_m \times 12 \\]

\\(R_m\\) is monthly rent.

2\. Effective annual rental income

\\[ E = G - V \\]

\\(V\\) represents estimated vacancy and lost rent.

3\. Net operating income (NOI)

\\[ NOI = E - O \\]

\\(O\\) represents operating expenses such as owner-paid maintenance, management fees, and other applicable operating costs. Financing costs and income taxes are normally excluded from NOI.

4\. Gross rental yield

\\[ Y_g = \frac{G}{P}\times100\\% \\]

5\. Net operating yield

\\[ Y_n = \frac{NOI}{P+C}\times100\\% \\]

Here, \\(P\\) is the purchase price and \\(C\\) is acquisition cost included in the chosen investment basis.

Example

Assume an illustrative property has:

- Purchase price: SAR 800,000
- Expected monthly rent: SAR 5,000
- Annual vacancy allowance: SAR 3,000
- Annual operating expenses: SAR 9,000
- Acquisition costs: SAR 40,000

Then:

| Calculation                        | Result     |
| ---------------------------------- | ---------- |
| Annual gross rent                  | SAR 60,000 |
| Effective annual rent              | SAR 57,000 |
| NOI                                | SAR 48,000 |
| Gross yield                        | 7.50%      |
| Net operating yield on SAR 840,000 | 5.71%      |

These figures are illustrative, not a forecast. The CRM should show which values are estimated and which are actual.

### C. Investment return calculations

An investor may care about more than rental yield.

1\. Cash-on-cash return

\\[ CoC = \frac{\text{Annual pre-tax cash flow}}{\text{Cash invested}}\times100\\% \\]

Annual pre-tax cash flow is typically NOI minus annual debt service, with any additional cash expenses accounted for consistently.

2\. Capital appreciation

\\[ A = \frac{P\_{\text{current}}-P\_{\text{purchase}}} {P\_{\text{purchase}}}\times100\\% \\]

This is the percentage change in estimated property value. It is not a realized profit until a sale occurs, and it excludes transaction costs unless they are separately included.

3\. Total investment return

For a simple one-period calculation:

\\[ ROI = \frac{\text{Net sale proceeds}+\text{Net rental cash flow}-\text{Initial cash invested}} {\text{Initial cash invested}}\times100\\% \\]

For multiple years, use a cash-flow schedule and consider IRR (internal rate of return) because the timing of cash inflows and outflows matters.

The CRM should not label gross rental yield as net profit, or treat an estimated property value as cash received.

### D. Business workflow equations and rules

These rules govern tasks, activities, communications, viewings, and transaction statuses.

| Rule                | Business logic                                                       | Expected CRM behavior                                                         |
| ------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| First-contact SLA   | `now - lead.created_at <= SLA`                                       | Assign and monitor the first-contact deadline                                 |
| Task completion     | Required outcome and required fields are present                     | Mark task complete only when the completion criteria are satisfied            |
| Viewing success     | Viewing is completed and outcome is recorded                         | Enable the next appropriate action, such as an offer or follow-up             |
| Offer acceptance    | Required parties and authorized approval confirm acceptance          | Allow the transaction to proceed to the next controlled stage                 |
| Reservation         | Unit is eligible, terms are valid, and required approval is obtained | Create or confirm the reservation and update availability according to policy |
| Contract completion | Required signatures and required checks are satisfied                | Mark the contract completed only when the defined conditions are met          |
| Payment completion  | Valid payment is confirmed and reconciled                            | Update the payment record and outstanding balance                             |
| Task overdue        | `now > due_at` and task remains open                                 | Escalate according to the assigned SLA and role                               |

The system's date and time should use a consistent timezone policy, with the organization's local timezone used for user-facing deadlines.

The most important rule: creating a task, sending a message, or scheduling a viewing must not, by itself, advance the lead or transaction to a later business status.

For example, sending an offer to a customer is not the same as the customer accepting the offer. An accepted offer is not necessarily the same as a confirmed reservation, and a reservation is not necessarily a completed contract.

### E. Financial and commission controls

Outstanding balance

\\[ Balance = AmountDue - AmountPaid \\]

The existing payment constraints require non-negative amounts and prevent `amount_paid` from exceeding `amount_due` for a payment record. If partial payments are needed, represent them consistently with the approved payment design rather than bypassing that constraint.

Commission calculation

\\[ Commission = CommissionBase \times Rate \\]

For example, if the approved commission base is SAR 800,000 and the illustrative commission rate is 2%, the calculated commission is SAR 16,000.

But the CRM must not assume that the commission base is always the sale price, or that the rate is always 2%. The commission policy must define the base, rate, responsible party, applicable taxes or fees, splits, approval, and when the commission becomes payable.

For rent transactions, the commission calculation may use a different base—for example, a fixed fee or a defined portion of rent—depending on the approved company policy and applicable rules.

Unit availability control

A unit must not be allocated to incompatible, overlapping reservations. The system should check for conflicting active reservations and apply the approved reservation policy within a database transaction. If the check fails, the system must not confirm the new reservation.

## 4. How tasks and activities should be generated for each customer type

Use workflow templates rather than manually inventing titles every time. The template provides the standard title, trigger, owner, due date rule, required outcome, and any follow-up action.

The examples below are recommended business rules, not a claim that these templates already exist in the approved database.

### Rental workflow

1\. Lead created — `RENT_LEAD_FIRST_CONTACT`

Task: `Rental Lead — First Contact`

The assigned agent contacts the customer and records the preferred area, rent budget, bedrooms, move-in date, and lease duration.

Outcome: no answer → schedule a retry; qualified → proceed to property matching; not interested → record the reason and close according to policy.

2\. Requirements confirmed — `RENT_MATCH_PROPERTIES`

Task: `Rental — Match Available Properties`

Find eligible available units and rank them using the matching score. Record recommendations and communications with the customer.

Outcome: suitable units found → propose options; none found → refine criteria or set a follow-up date.

3\. Viewing arranged — `RENT_VIEWING_FOLLOW_UP`

Task: `Rental — Confirm Viewing and Follow Up`

Use `viewings` for the scheduled appointment and record the actual outcome. If the customer requests a new time, reschedule instead of recording a successful viewing.

Outcome: interested → discuss terms; not interested → record feedback and find alternatives; did not attend → schedule follow-up.

4\. Rental terms agreed — `RENT_PREPARE_TENANCY`

Task: `Rental — Prepare Tenancy Agreement`

Validate the approved rental terms, documentation, approvals, and payment obligations. Create or update the appropriate tenancy records only at the correct stage.

Outcome: agreement executed → activate the tenancy under policy; terms rejected → return to negotiation or close the opportunity.

5\. Tenancy active — `RENT_COLLECTION_MONITORING`

Task: `Rental — Monitor Rent Collection`

Generate reminders based on actual rent due dates and payment status. Monitor arrears, lease expiry, renewals, and maintenance requests.

Outcome: payment reconciled → update collection status; overdue → follow the approved escalation procedure.

### Buying workflow

| Trigger                   | Standard task title                               | Completion condition                                                            |
| ------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| Buyer lead qualified      | `Buyer — Confirm Requirements`                    | Budget, preferred locations, property type, and purchase timeline are recorded  |
| Requirements confirmed    | `Buyer — Match Available Properties`              | Eligible candidate units have been evaluated                                    |
| Viewing completed         | `Buyer — Record Viewing Feedback`                 | Customer feedback and next action are recorded                                  |
| Customer wants to proceed | `Buyer — Prepare Offer`                           | Offer terms and required approvals are complete                                 |
| Offer received            | `Buyer — Negotiate Offer`                         | Accepted, rejected, countered, or withdrawn outcome is recorded                 |
| Offer accepted            | `Buyer — Verify Reservation Requirements`         | Reservation conditions and unit eligibility are checked                         |
| Reservation confirmed     | `Buyer — Coordinate Contract Completion`          | Required documentation, approvals, signatures, and payment checks are satisfied |
| Contract completed        | `Buyer — Complete Handover and Commission Checks` | Handover and applicable financial controls are completed                        |

A declined offer should not automatically close the entire lead: the customer may still want another property. Likewise, a failed reservation should release a unit only when the reservation cancellation or expiry process is valid and the unit is not otherwise committed.

### Investment workflow

| Trigger                     | Standard task title                           | Completion condition                                                             |
| --------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------- |
| Investment lead qualified   | `Investment — Confirm Investment Objectives`  | Budget, investment horizon, risk preferences, and return objectives are recorded |
| Objectives confirmed        | `Investment — Compare Property Returns`       | Comparable properties have consistent, documented assumptions                    |
| Candidate selected          | `Investment — Validate Financial Assumptions` | Rent, vacancy, operating expenses, financing, and acquisition costs are reviewed |
| Customer approves candidate | `Investment — Prepare Acquisition Offer`      | Offer and approval requirements are complete                                     |
| Acquisition completed       | `Investment — Establish Performance Baseline` | Purchase cost, forecast rent, costs, and target returns are recorded             |
| Property rented             | `Investment — Monitor Actual Returns`         | Actual collections, expenses, vacancy, and performance variance are reviewed     |
| Review date reached         | `Investment — Review Portfolio Performance`   | Return variance and recommended next action are recorded                         |

An investment analysis should preserve the assumptions used to calculate a return. Otherwise, when the asking price, rent forecast, or expense assumptions change, the CRM cannot explain why a previous recommendation was made.

## 5. How the four tables work together

Your approved schema includes `tasks`, `activities`, `communications`, and `viewings`. They should work together, but each has a different responsibility.

| Table            | Purpose                                       | Example                                      |
| ---------------- | --------------------------------------------- | -------------------------------------------- |
| `tasks`          | Work that someone must perform                | Call the rental customer tomorrow            |
| `activities`     | Work performed or planned business activity   | Record the qualification call and its result |
| `communications` | A record of customer communication            | Store the outbound email or inbound message  |
| `viewings`       | A property viewing appointment and its result | Schedule a viewing for Unit A-101            |

Consider a customer who wants to rent a unit:

1. The lead is created.
2. The CRM generates `Rental Lead — First Contact`.
3. The agent calls the customer.
4. The system records the activity and, where supported, the communication record.
5. If the customer does not answer, the task result triggers a retry task with a new due date.
6. If the customer qualifies, the CRM enables property matching.
7. The agent schedules a viewing, creating a `viewings` record.
8. After the viewing, the agent records the outcome.
9. The outcome determines the next task: negotiate terms, find alternatives, or follow up later.

There is an important technical distinction here: your current `communications` table does not directly link to an `opportunity`, according to the existing schema notes. If you need every communication to be traceable to a specific opportunity, document that as a requirement and decide whether an approved schema change is necessary.

## 6. How the CRM should decide the next action

The most useful implementation is an event-driven workflow.

```

# Illustrative business logic, not production-ready code.

def handle_viewing_completed(viewing):
    if viewing.outcome == "INTERESTED":
        ensure_open_task(
            key=f"VIEWING_INTERESTED:{viewing.viewing_id}",
            title="Viewing — Discuss Next Steps",
            owner=viewing.agent_user_id
        )

    elif viewing.outcome == "NOT_INTERESTED":
        ensure_open_task(
            key=f"VIEWING_ALTERNATIVES:{viewing.viewing_id}",
            title="Viewing — Find Alternative Properties",
            owner=viewing.agent_user_id
        )

    elif viewing.outcome == "RESCHEDULE_REQUESTED":
        ensure_open_task(
            key=f"VIEWING_RESCHEDULE:{viewing.viewing_id}",
            title="Viewing — Reschedule Appointment",
            owner=viewing.agent_user_id
        )

    # Do not mark the opportunity won merely because
    # a viewing was completed or the customer was interested.

```

The exact values for `outcome` must match the approved schema and the application's allowed values. The function `ensure_open_task` is illustrative; it should enforce deduplication so that processing the same event twice does not create duplicate tasks.

A production implementation should also:

- Validate permissions before any state-changing operation.
- Use database transactions for related changes that must succeed together.
- Keep an audit record of important status transitions.
- Send notifications after the database transaction commits.
- Handle retries and duplicate events safely.
- Require explicit completion outcomes for important tasks.
- Preserve the distinction between forecast, approval, commitment, and completed transaction.

## 7. Equations for managers and team performance

The same business data can drive dashboards for agents, branch managers, sales directors, and the general manager.

Lead contact SLA compliance

\\[ SLA\\% = \frac{\text{Leads contacted within SLA}} {\text{Eligible leads due for contact}}\times100 \\]

This shows whether the team is contacting new leads on time. Define which leads count in the denominator, including how cancelled, duplicate, and out-of-hours leads are treated.

Lead-to-transaction conversion

\\[ Conversion\\% = \frac{\text{Qualified leads achieving the defined outcome}} {\text{Qualified leads in the same cohort}}\times100 \\]

Choose a specific outcome, such as completed rental contracts or completed sales contracts. Track cohorts consistently rather than dividing this month's contracts by this month's newly created leads.

Task completion rate

\\[ Completion\\% = \frac{\text{Tasks completed by the reporting cutoff}} {\text{Tasks due by the reporting cutoff}}\times100 \\]

Report overdue tasks separately. A task completed after its deadline should not count as on-time completion.

Viewing-to-offer conversion

\\[ Conversion\\% = \frac{\text{Eligible completed viewings followed by an offer}} {\text{Eligible completed viewings}}\times100 \\]

Use a defined attribution window and avoid counting multiple offers or repeated viewings inconsistently.

Forecast versus actual rental income

\\[ Variance = ActualIncome - ForecastIncome \\]

\\[ Variance\\% = \frac{ActualIncome-ForecastIncome} {ForecastIncome}\times100 \\]

If forecast income is zero, show the percentage variance as unavailable rather than dividing by zero.

### Which roles should receive these results?

- Agent: next tasks, customer follow-ups, viewings, offers, and personal SLA performance.
- Branch manager: overdue tasks, leads without contact, stalled opportunities, unit availability conflicts, and conversion by agent.
- Sales director: pipeline value, conversion by transaction type, offer acceptance, and time to completion.
- Finance: payment reconciliation, outstanding balances, commissions due, and approved financial reports.
- Property management: tenancy expiries, rent collection, arrears, maintenance tickets, and renewals.
- General manager: branch performance, revenue, profitability where the necessary data exists, forecast versus actual results, and escalations.

Do not calculate company-wide revenue from offers or reservations alone. Those are pipeline or commitment indicators; actual revenue and cash collection require their own clearly defined accounting rules.

## 8. My recommended implementation for your existing 47-table CRM

Build this in layers, without silently modifying your approved schema.

1. Purpose and opportunity rules. Define rental, purchase, and investment workflows, including how one customer can have multiple opportunities.
2. Workflow catalog. Standardize task titles, event triggers, owners, due-date rules, completion outcomes, and deduplication keys.
3. State transition rules. Define which actions can move a lead, opportunity, viewing, offer, reservation, contract, or tenancy forward or backward.
4. Calculation service. Centralize property matching, rental yield, investment returns, affordability, commission, and performance calculations. Store the assumptions used for financial forecasts.
5. Automation and escalation. Generate tasks and notifications, handle retries, monitor SLAs, and escalate overdue work to the correct role.
6. Audit and testing. Test successful transactions, declined offers, failed reservations, overdue tasks, payment errors, unavailable units, duplicate events, and simultaneous attempts to reserve the same unit.

Some of these features can be implemented in application code using your existing 47 tables. If a requirement cannot be represented safely—for example, recording investment assumptions historically or configuring reusable workflow templates—raise a separate, documented schema-change proposal.

My strongest recommendation: make the workflow engine the central controller of business actions, while keeping financial calculations in a separate, testable service. This will prevent an agent's routine action—such as sending a message or completing a viewing—from accidentally changing a contract, reservation, payment, or unit status.

The next design artifact should be a Business Rules and Workflow Matrix with one row per rule and columns for trigger, condition, equation, task title, owner, affected table, permitted status transition, approval, notification, and failure handling. That matrix can then guide both your backend implementation and your AI coding agent without changing the approved database by assumption.&#x20;
