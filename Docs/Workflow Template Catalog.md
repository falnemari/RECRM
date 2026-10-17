Workflow Template Catalog.md

Every recurring task or communication template should have
1. a stable identifier
2. standard title/subject
3. trigger
4. owner role
5. due-time rule
6. completion criteria
7. escalation rule.

Stage A — Customer and Lead creation. ---> Objective: Capture the inquiry correctly and ensure someone owns it.

Type		Standard title/subject			Owner				Trigger
Task		Lead — First Contact			Assigned sales agent		Lead created and assigned
Activity	Lead — Created				System or creator		Lead successfully created
Activity	Lead — Assigned				System or assigning manager	Assignment succeeds
Communication	Lead — Initial Contact			Assigned agent			Agent initiates approved customer contact
Task		Lead — Complete Missing Information	Assigned agent			Required qualification data is missing

Business effects
- customers: create or reuse the customer record after checking for duplicates.
- leads: record the inquiry, source, requirements, assigned user and response deadline.
- tasks: create the first-contact task.
- activities: record lead creation and assignment.
- communications: create a record only when a communication event actually occurs.
Do not mark the lead as contacted simply because the system created a task or drafted a message.
If a duplicate customer is detected, the CRM should alert the employee and follow the approved deduplication process rather than silently creating a second customer.

Stage B — First contact and qualification. ---> Objective: Determine what the customer needs and whether the inquiry is ready for a sales opportunity.
Type		Standard title/subject		Owner		Trigger
Task		Lead — First Contact		Sales agent	Existing task
Activity	Lead — First Contact Attempt	Sales agent	Attempt actually made
Communication	Lead — Initial Contact		Sales agent	Message actually sent
Task		Lead — Retry Contact		Sales agent	No answer or failed contact, where policy allows
Activity	Lead — Qualified		Sales agent	Qualification criteria satisfied
Task		Lead — Complete Qualification	Sales agent	Information needed to qualify remains missing

Use structured contact outcomes, for example:
- CONNECTED
- NO_ANSWER
- INVALID_CONTACT
- CALLBACK_REQUESTED
- QUALIFIED
- NOT_QUALIFIED
These are proposed values; align them with the application's approved status/outcome conventions.
Business effects
- A successful conversation may populate missing customer requirements.
- A failed attempt may schedule a retry, subject to contact limits and customer preferences.
- A qualified lead may become eligible for an opportunities record.
- An unqualified lead should only be closed or disqualified after the reason is recorded according to policy.
- A missed SLA should notify the responsible agent and, after the configured escalation threshold, the branch manager.
Do not create an endless chain of reminders. Use a maximum retry policy, escalation, and a terminal outcome such as unreachable or disqualified where justified.

Stage C — Create opportunity and match properties. ---> Objective: Turn a qualified inquiry into a managed sales pipeline item.
Type		Standard title/subject			Owner			Trigger
Activity	Opportunity — Created			Assigned agent/system	Opportunity successfully created
Task		Opportunity — Match Properties		Sales agent		Opportunity enters matching stage
Activity	Opportunity — Properties Presented	Sales agent		Matching options actually presented
Communication	Opportunity — Property Recommendations	Sales agent		Recommendations sent to customer
Task		Opportunity — Arrange Viewing		Sales agent		Customer selects a unit or requests a viewing

Business effects
- opportunities: stores the sales pipeline record and its stage.
- opportunity_units: links the opportunity to candidate or selected units according to the application's matching rules.
- units: remains in its actual inventory status; matching a unit does not reserve it.
- activities and communications: preserve the record of what was presented and communicated.
- tasks: ensure the agent follows up on the proposed properties.
If the customer changes budget, city or property type, update the customer's requirements or lead/opportunity data according to the approved ownership of those fields. Re-run matching without automatically changing a unit's status.


Stage D — Viewing / property inspection. ---> Objective: Schedule the viewing, ensure attendance, record feedback, and agree on the next action.
Type		Standard title/subject			Owner			Trigger
Task		Viewing — Confirm Appointment		Sales agent		Viewing scheduled
Communication	Viewing — Appointment Confirmation	Sales agent/system	Appointment details are ready to send
Task		Viewing — Customer Reminder		Sales agent/system	Configured reminder time reached
Activity	Viewing — Appointment Confirmed		Agent/system		Confirmation actually received
Activity	Viewing — Completed			Sales agent		Viewing actually completed
Activity	Viewing — Outcome Recorded		Sales agent		Feedback and outcome recorded
Task		Viewing — Follow-up			Sales agent		Viewing completed and follow-up is required
Communication	Viewing — Follow-up Message		Sales agent		Approved follow-up message sent

Business effects
- viewings: update appointment time, status, outcome and notes.
- activities: record confirmation, attendance, completion and meaningful outcomes.
- communications: record actual appointment messages and follow-ups.
- tasks: create reminders and follow-up actions.
- opportunities: progress only when the outcome and business rules justify it.
- leads: change only if the lead lifecycle policy explicitly requires it.
If the customer cancels, record cancellation and its reason. If the customer does not attend, record the no-show and create a rescheduling task where appropriate.
A viewing being marked COMPLETED must not automatically mean the customer is interested. Its outcome must capture the actual result.

Stage E — Offer, negotiation and approval
Objective: Record the customer's commercial proposal and obtain the required decisions.
Type	Standard title/subject	Owner	Trigger
Task	Offer — Prepare Proposal	Sales agent	Customer requests an offer
Activity	Offer — Created	Sales agent/system	Offer record created
Communication	Offer — Proposal Sent	Sales agent	Proposal actually sent
Task	Offer — Follow-up Before Expiry	Sales agent	Offer remains pending near expiry
Task	Offer — Manager Approval	Authorized manager	Offer exceeds the agent's approval authority
Activity	Offer — Decision Recorded	Decision-maker/system	Offer accepted, rejected or countered
Communication	Offer — Decision Communicated	Sales agent	Decision communicated to customer
Business effects
- offers: records the proposal, amount, validity and decision.
- opportunities: progresses through the approved sales stages.
- tasks: ensure the proposal is followed up before its expiry.
- activities: document decisions and negotiation milestones.
- communications: preserve actual messages sent to the customer.
- audit_logs: record sensitive approvals or changes where required by the security policy.
A customer saying “I accept” in a conversation does not necessarily mean that all internal approvals or reservation conditions have been satisfied. Record the response, validate the required conditions, and then advance the transaction.
Stage F — Reservation and financial coordination
Objective: Protect the selected unit, track reservation deadlines and coordinate financial requirements.
Type	Standard title/subject	Owner	Trigger
Task	Reservation — Verify Unit Availability	Sales agent / authorized operations	Reservation requested
Activity	Reservation — Availability Verified	System/authorized employee	Availability check succeeds
Task	Reservation — Complete Required Documents	Sales agent	Required documents missing
Task	Reservation — Deposit Follow-up	Sales agent / Finance	Deposit is due or outstanding
Communication	Reservation — Confirmation	Sales agent	Reservation is confirmed
Task	Reservation — Expiry Review	Assigned agent / manager	Reservation approaches expiry
Activity	Reservation — Confirmed	System/authorized employee	Reservation successfully committed
Business effects
- reservations: create or update the reservation and its expiry.
- units and unit_status_history: update inventory status only as defined by the approved reservation rules.
- payments: record actual financial obligations and receipts according to the approved payment model.
- contracts: create only after reservation and contract prerequisites are met.
- Finance: receives an action or notification when payment verification or reconciliation is required.
- Branch manager: receives an escalation for an expiring reservation or unresolved exception.
Important financial distinction: a reservation, an invoice or amount due, and money actually received are different facts. The system must not mark a deposit as paid merely because a reservation was created or a payment task was completed. Payment status should reflect a recorded and appropriately verified financial transaction.
Reservation availability must be checked transactionally to prevent two agents from successfully reserving the same unit at the same time. This is consistent with the approved database specification. DATABASE.md

Stage G — Contract preparation, signing and closure
Objective: Prepare the agreement, complete required checks, record execution and hand over the transaction.
Type	Standard title/subject	Owner	Trigger
Task	Contract — Prepare Draft	Legal/contracts or authorized agent	Reservation meets contract prerequisites
Activity	Contract — Draft Created	Legal/contracts	Draft actually created
Task	Contract — Internal Review	Authorized reviewer	Draft ready for review
Communication	Contract — Review Required	Internal notification recipient	Review action assigned
Task	Contract — Customer Signature	Assigned agent/legal	Final contract ready for signature
Communication	Contract — Signature Instructions	Assigned agent	Signing instructions actually sent
Activity	Contract — Signed	Authorized employee/system	Signature verified and recorded
Task	Contract — Payment and Reconciliation	Finance	Contract establishes financial obligations
Task	Contract — Finalize Handover	Sales operations / relevant team	Required signing and financial checks complete
Activity	Contract — Closed	Authorized employee/system	Closure conditions satisfied
Business effects
- contracts: stores the agreement and its lifecycle state.
- reservations: preserves the link between reservation and contract.
- payments: tracks contractual payment obligations and actual receipts.
- commissions: tracks applicable commission calculations, approvals and payment status.
- documents: stores contract document metadata and version information.
- opportunities: advances to the correct closing stage under the approved pipeline.
- units: updates inventory status according to the actual transaction and property rules.
- audit_logs: records sensitive contract, financial and approval actions.
A signed contract should not automatically mark every payment as received, every commission as paid, or every handover task as complete. Each represents a separate business fact and needs its own evidence and completion rule.

4. How to guide the entire team without overwhelming them
I would use one workflow, role-based responsibility, and different views of the same underlying records. Avoid creating a separate duplicate task for every manager who needs visibility.
Role	What the CRM should show	Typical action
Sales agent	Assigned leads, today's tasks, upcoming viewings, pending offers, overdue follow-ups	Contact, qualify, arrange viewing, negotiate
Branch manager	Unassigned leads, SLA breaches, overdue tasks, viewing conversion, stalled opportunities, expiring reservations	Reassign work, coach agents, approve within authority, escalate
Sales director	Pipeline by stage, conversion, forecast, agent performance, lost reasons	Manage pipeline, resolve bottlenecks, review exceptions
General manager	Executive KPIs, sales performance, revenue/collection summaries, major overdue issues, escalations	Decide priorities, resolve cross-team blockers
Accountant / Finance	Deposits, payment obligations, received amounts, reconciliation exceptions, commissions	Verify receipts, reconcile payments, process approved finance steps
Legal / Contracts	Drafts awaiting review, missing documents, signatures, contract exceptions	Review, approve, issue or finalize agreements
Marketing	Lead source, campaign attribution, response and conversion trends	Optimize campaigns and lead quality
Call center	New leads, contact SLA, callbacks, failed attempts	Capture, contact and route leads
Property / inventory team	Unit availability, viewing activity, reservations, contract-related inventory changes	Confirm inventory data and resolve unit conflicts
The notification rule I recommend
- Assigned employee: receives the actionable task and its due date.
- Branch manager: receives exceptions, SLA breaches and overdue escalations, not every routine activity.
- Sales director: receives stage bottlenecks, approval requests within their authority, and pipeline exceptions.
- General manager: receives concise dashboards and material escalations rather than every customer message.
- Finance: receives payment and reconciliation work when a real financial trigger occurs.
- Legal: receives contract-review work when the draft reaches the review stage.
The CRM should distinguish a notification from a task. A notification tells someone something happened; a task assigns an action with an owner, due date, status and completion criteria.
For example, “Reservation expires in 24 hours” may be a notification to the agent and branch manager. “Contact the customer and resolve the reservation decision” is the task. Do not create a separate task for every recipient unless each person has a distinct responsibility.
5. How results should affect other tables
This is where I would be strict with the Coding Agent. Every workflow action must have a defined result and an explicit rule describing which business records it may change.
Event/result	Record to update	Follow-up behavior
Lead assigned	leads	Create first-contact task; notify assigned agent
First contact attempted, no answer	activities	Complete contact task with outcome; schedule retry if allowed
Customer replies	communications	Record message; create a task only if a response/action is required
Lead qualifies	leads, opportunities	Update qualification status; create opportunity if one does not already exist for that workflow
Viewing scheduled	viewings	Create confirmation/reminder tasks; send confirmation where appropriate
Viewing completed	viewings, activities	Record outcome; create follow-up task based on outcome
Offer submitted	offers, opportunities	Set the appropriate stage; schedule follow-up before expiry
Offer approved	offers	Notify the agent; permit the next step if other prerequisites are satisfied
Reservation confirmed	reservations, potentially units, unit_status_history	Start expiry monitoring and financial follow-up
Payment verified	payments	Update payment status/amount according to the actual transaction; notify the relevant team
Contract signed	contracts	Trigger finance and closure tasks; update opportunity/unit only according to approved rules
Task overdue	tasks	Notify the assignee; escalate according to policy
Approval rejected	Relevant business record	Record the decision/reason and create a corrective task if needed
The table describes recommended orchestration. The precise fields to update must follow the actual migration definitions and approved business rules.
One important technical rule: use transactions
Suppose a reservation is confirmed. The application may need to:
1. Verify the unit is still available.
2. Create the reservation.
3. Update the unit's status.
4. Add a unit status history record.
5. Create the required follow-up task.
6. Record the audit event.
The database changes that form the core business transaction should be committed atomically wherever possible. Notifications should be dispatched reliably after commit, rather than being sent before the reservation succeeds.
The same principle applies to contract creation and payment posting.
6. Make the recurring workflow configurable
Your existing approved database contains activities, communications, and tasks, but it does not itself define a complete workflow-template engine, notification queue, or configurable escalation system. These need to be implemented in the application/infrastructure layer or added later through an approved schema change. DATABASE.md

I would ask the Coding Agent to implement a configuration model conceptually like this:
Workflow Template
Defines what should happen when a business event occurs.

Template ID: VIEWING_FOLLOW_UP
Standard title: Viewing — Follow-up
Trigger: Viewing completed
Owner rule: Assigned sales agent
Due rule: Configurable, e.g. within one business day
Completion rule: Contact outcome recorded and next action decided
Escalation: Notify branch manager if overdue beyond policy threshold
Deduplication: Do not create a duplicate open task for the same viewing and trigger

The template is not itself a task. It defines how the application generates individual task instances.
For example, the same VIEWING_FOLLOW_UP template can create separate tasks for Ahmed's viewing and Sara's viewing, while retaining the same standard title.
7. Define task completion outcomes, not just Open and Completed
A checkbox labelled “Done” is insufficient for many real-estate workflows.
For contact tasks, the agent should select an outcome such as:
- Connected and qualified.
- Connected; follow-up required.
- No answer.
- Wrong or invalid contact.
- Customer declined.
- Customer requested a callback.
For a viewing follow-up:
- Interested — prepare offer.
- Interested — another viewing required.
- Needs more information.
- Not interested — record reason.
- Viewing must be rescheduled.
The application can then determine the next recommended action. It should not infer a successful outcome from task completion alone.
For example:
Task: Viewing — Follow-up
Outcome: Interested — Prepare Offer

Result:
    Update viewing outcome
    Record activity
    Create Offer — Prepare Proposal task
    Notify assigned agent
    Keep opportunity stage governed by the approved pipeline


Another outcome:
Task: Viewing — Follow-up
Outcome: Not Interested

Result:
    Record viewing outcome
    Record the reason
    Create a property-matching task if appropriate
    Do not automatically close the lead


This is how the CRM can help employees make consistent decisions while keeping the business record accurate.

8. My final recommendation for your CRM
I would implement this in four layers:

Layer 1 — Business workflow
Defines the stages, permitted transitions, required outcomes, approvals and exit conditions.




Layer 2 — Task and activity engine
Creates actionable work, records completed actions, assigns ownership and prevents duplicate tasks.




Layer 3 — Communication and notification engine
Sends approved customer messages, internal alerts, reminders and escalations, with delivery results where supported.




Layer 4 — Business data and audit
Updates leads, opportunities, viewings, reservations, contracts and payments according to explicit rules, recording sensitive changes for audit.



What I would insist the Coding Agent deliver
1. A workflow definition for every stage from lead creation to contract closure.
2. A catalog of standardized task titles, activity subjects and communication templates.
3. Configurable due dates, business hours, SLA thresholds and escalation rules.
4. A clear owner for every task, with manager escalation where necessary.
5. Defined completion outcomes and the resulting business-record updates.
6. Duplicate prevention and safe retry behavior.
7. Role-based dashboards and notifications for the entire real-estate team.
8. An audit trail for important state transitions and approvals.
9. Automated tests proving that each event changes only the permitted records.
10. No changes to the approved 47-table schema without an explicit, documented change request.
The key design decision is this: the CRM should guide employees through a repeatable process, but it must never confuse a reminder with an action, a message with a confirmed outcome, or a completed task with a completed business transaction.
That distinction is what will make your CRM useful to agents, managers, finance and the general manager—not merely a collection of data-entry screens.
