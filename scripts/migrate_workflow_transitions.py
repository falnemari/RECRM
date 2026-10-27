"""
Migration & Seeding Script: Dynamic Workflow Transitions (next_template_id & outcome_transitions)
==================================================================================================
Adds:
1. workflow_templates.next_template_id (VARCHAR(100) REFERENCES workflow_templates(template_id) ON DELETE SET NULL)
2. workflow_templates.outcome_transitions (JSONB DEFAULT NULL)

Seeds all 52 TASK templates with explicit transition graphs:
- Identifies Root/Entry tasks (no incoming transitions).
- Configures Intermediate tasks with standard and branching outcomes.
- Explicitly marks Terminal & Standalone Consultative tasks with NULL (no successor).
"""

import asyncio
import json
import asyncpg

TRANSITIONS_CATALOG = {
    # -------------------------------------------------------------------------
    # 1. Lead Qualification Pipeline (Entry & Common Routing)
    # -------------------------------------------------------------------------
    "TASK_LEAD_ASSIGN": {
        "next": "TASK_LEAD_FIRST_CONTACT",
        "outcomes": {
            "ASSIGNED": "TASK_LEAD_FIRST_CONTACT",
            "RENT": "TASK_RENT_LEAD_FIRST_CONTACT",
            "INVESTMENT": "TASK_INVEST_LEAD_FIRST_CONTACT"
        }
    },
    "TASK_LEAD_FIRST_CONTACT": {
        "next": "TASK_LEAD_QUALIFY",
        "outcomes": {
            "CONNECTED": "TASK_LEAD_QUALIFY",
            "QUALIFIED": "TASK_LEAD_QUALIFY",
            "NO_ANSWER": "TASK_LEAD_FOLLOWUP",
            "BUSY": "TASK_LEAD_FOLLOWUP",
            "UNREACHABLE": "TASK_LEAD_FOLLOWUP",
            "CALLBACK_REQUESTED": "TASK_LEAD_FOLLOWUP",
            "DISQUALIFIED": None,
            "NOT_INTERESTED": None,
            "INVALID_CONTACT": None
        }
    },
    "TASK_RENT_LEAD_FIRST_CONTACT": {
        "next": "TASK_LEAD_QUALIFY",
        "outcomes": {
            "CONNECTED": "TASK_LEAD_QUALIFY",
            "QUALIFIED": "TASK_LEAD_QUALIFY",
            "NO_ANSWER": "TASK_LEAD_FOLLOWUP",
            "BUSY": "TASK_LEAD_FOLLOWUP",
            "UNREACHABLE": "TASK_LEAD_FOLLOWUP",
            "CALLBACK_REQUESTED": "TASK_LEAD_FOLLOWUP",
            "DISQUALIFIED": None,
            "NOT_INTERESTED": None
        }
    },
    "TASK_INVEST_LEAD_FIRST_CONTACT": {
        "next": "TASK_INVEST_CONFIRM_OBJECTIVES",
        "outcomes": {
            "CONNECTED": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "QUALIFIED": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "NO_ANSWER": "TASK_LEAD_FOLLOWUP",
            "BUSY": "TASK_LEAD_FOLLOWUP",
            "UNREACHABLE": "TASK_LEAD_FOLLOWUP",
            "CALLBACK_REQUESTED": "TASK_LEAD_FOLLOWUP",
            "DISQUALIFIED": None,
            "NOT_INTERESTED": None
        }
    },
    "TASK_LEAD_FOLLOWUP": {
        "next": "TASK_LEAD_QUALIFY",
        "outcomes": {
            "CONNECTED": "TASK_LEAD_QUALIFY",
            "QUALIFIED": "TASK_LEAD_QUALIFY",
            "NO_ANSWER": "TASK_LEAD_FOLLOWUP",
            "BUSY": "TASK_LEAD_FOLLOWUP",
            "UNREACHABLE": None,
            "DISQUALIFIED": None,
            "NOT_INTERESTED": None
        }
    },
    "TASK_LEAD_QUALIFY": {
        "next": "TASK_VIEWING_SCHEDULE",
        "outcomes": {
            "QUALIFIED": "TASK_VIEWING_SCHEDULE",
            "CONVERTED": "TASK_VIEWING_SCHEDULE",
            "QUALIFIED_SALE": "TASK_VIEWING_SCHEDULE",
            "QUALIFIED_RENT": "TASK_RENT_MATCH_PROPERTIES",
            "QUALIFIED_INVESTMENT": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "FOLLOWUP_NEEDED": "TASK_LEAD_FOLLOWUP",
            "NO_ANSWER": "TASK_LEAD_FOLLOWUP",
            "DISQUALIFIED": None,
            "NOT_INTERESTED": None,
            "LOST": None
        }
    },
    "TASK_LEAD_COMPLETE_INFO": {
        "next": None,  # Standalone helper task (Terminal)
        "outcomes": None
    },

    # -------------------------------------------------------------------------
    # 2. Sales Pipeline
    # -------------------------------------------------------------------------
    "TASK_OPPORTUNITY_MATCH_PROPERTIES": {
        "next": "TASK_VIEWING_SCHEDULE",
        "outcomes": {
            "MATCHED": "TASK_VIEWING_SCHEDULE",
            "NONE_FOUND": None,
            "REVISE_CRITERIA": None
        }
    },
    "TASK_VIEWING_SCHEDULE": {
        "next": "TASK_VIEWING_REPORT",
        "outcomes": {
            "SCHEDULED": "TASK_VIEWING_REPORT",
            "RESCHEDULED": "TASK_VIEWING_RESCHEDULE",
            "CANCELLED": None
        }
    },
    "TASK_VIEWING_RESCHEDULE": {
        "next": "TASK_VIEWING_REPORT",
        "outcomes": {
            "SCHEDULED": "TASK_VIEWING_REPORT",
            "CANCELLED": None
        }
    },
    "TASK_VIEWING_REPORT": {
        "next": "TASK_OFFER_SUBMIT",
        "outcomes": {
            "INTERESTED": "TASK_OFFER_SUBMIT",
            "OFFER_REQUESTED": "TASK_OFFER_SUBMIT",
            "NEEDS_ANOTHER_UNIT": "TASK_VIEWING_SCHEDULE",
            "NOT_INTERESTED": None,
            "NO_SHOW": "TASK_VIEWING_RESCHEDULE",
            "CANCELLED": None
        }
    },
    "TASK_OFFER_PREPARE": {
        "next": "TASK_OFFER_FOLLOWUP",
        "outcomes": {
            "SUBMITTED": "TASK_OFFER_FOLLOWUP",
            "REQUIRES_APPROVAL": "TASK_OFFER_MANAGER_APPROVAL"
        }
    },
    "TASK_OFFER_SUBMIT": {
        "next": "TASK_OFFER_FOLLOWUP",
        "outcomes": {
            "SUBMITTED": "TASK_OFFER_FOLLOWUP",
            "REQUIRES_APPROVAL": "TASK_OFFER_MANAGER_APPROVAL"
        }
    },
    "TASK_OFFER_MANAGER_APPROVAL": {
        "next": "TASK_OFFER_FOLLOWUP",
        "outcomes": {
            "APPROVED": "TASK_OFFER_FOLLOWUP",
            "REJECTED": "TASK_OFFER_PREPARE"
        }
    },
    "TASK_OFFER_FOLLOWUP": {
        "next": "TASK_RESERVATION_VERIFY_AVAILABILITY",
        "outcomes": {
            "ACCEPTED": "TASK_RESERVATION_VERIFY_AVAILABILITY",
            "OFFER_ACCEPTED": "TASK_RESERVATION_VERIFY_AVAILABILITY",
            "COUNTER_OFFER": "TASK_SALE_NEGOTIATE_CONCESSIONS",
            "NEGOTIATION": "TASK_SALE_NEGOTIATE_CONCESSIONS",
            "REJECTED": "TASK_OPPORTUNITY_MATCH_PROPERTIES",
            "EXPIRED": "TASK_OPPORTUNITY_MATCH_PROPERTIES"
        }
    },
    "TASK_SALE_NEGOTIATE_CONCESSIONS": {
        "next": "TASK_OFFER_PREPARE",
        "outcomes": {
            "AGREED": "TASK_RESERVATION_VERIFY_AVAILABILITY",
            "COUNTER_PREPARED": "TASK_OFFER_PREPARE",
            "FAILED": "TASK_OPPORTUNITY_MATCH_PROPERTIES"
        }
    },
    "TASK_RESERVATION_VERIFY_AVAILABILITY": {
        "next": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
        "outcomes": {
            "AVAILABLE": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
            "CONFIRMED": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
            "UNAVAILABLE": "TASK_OPPORTUNITY_MATCH_PROPERTIES"
        }
    },
    "TASK_RESERVATION_DEPOSIT_FOLLOWUP": {
        "next": "TASK_CONTRACT_DRAFT",
        "outcomes": {
            "DEPOSIT_VERIFIED": "TASK_CONTRACT_DRAFT",
            "VERIFIED": "TASK_CONTRACT_DRAFT",
            "PAID": "TASK_CONTRACT_DRAFT",
            "CANCELLED": None,
            "EXPIRED": "TASK_RESERVATION_EXPIRY_REVIEW"
        }
    },
    "TASK_RESERVATION_DOCUMENTS": {
        "next": "TASK_CONTRACT_DRAFT",
        "outcomes": {
            "COMPLETED": "TASK_CONTRACT_DRAFT"
        }
    },
    "TASK_RESERVATION_EXPIRY_REVIEW": {
        "next": None,
        "outcomes": {
            "EXTENDED": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
            "RELEASED": None,
            "CANCELLED": None
        }
    },
    "TASK_CONTRACT_DRAFT": {
        "next": "TASK_CONTRACT_INTERNAL_REVIEW",
        "outcomes": {
            "DRAFTED": "TASK_CONTRACT_INTERNAL_REVIEW",
            "SUBMITTED": "TASK_CONTRACT_INTERNAL_REVIEW"
        }
    },
    "TASK_CONTRACT_INTERNAL_REVIEW": {
        "next": "TASK_CONTRACT_SIGNATURE",
        "outcomes": {
            "APPROVED": "TASK_CONTRACT_SIGNATURE",
            "APPROVED_DRAFT": "TASK_CONTRACT_SIGNATURE",
            "REJECTED": "TASK_CONTRACT_DRAFT",
            "REVISIONS_NEEDED": "TASK_CONTRACT_DRAFT"
        }
    },
    "TASK_CONTRACT_SIGNATURE": {
        "next": "TASK_CONTRACT_HANDOVER",
        "outcomes": {
            "SIGNED": "TASK_CONTRACT_HANDOVER",
            "RECORD_SIGNATURE": "TASK_CONTRACT_HANDOVER"
        }
    },
    "TASK_CONTRACT_HANDOVER": {
        "next": None,  # Terminal Task: Deal Closed & Unit Handed Over
        "outcomes": None
    },
    "TASK_SALE_TITLE_DEED_VERIFICATION": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_SALE_MORTGAGE_PREQUALIFICATION": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_SALE_DEFECTS_DISCLOSURE": {
        "next": None,  # Standalone Statutory Task
        "outcomes": None
    },

    # -------------------------------------------------------------------------
    # 3. Rental Pipeline
    # -------------------------------------------------------------------------
    "TASK_RENT_MATCH_PROPERTIES": {
        "next": "TASK_VIEWING_SCHEDULE",
        "outcomes": {
            "MATCHED": "TASK_VIEWING_SCHEDULE",
            "NONE_FOUND": None
        }
    },
    "TASK_RENT_VIEWING_FOLLOW_UP": {
        "next": "TASK_RENT_PREPARE_TENANCY",
        "outcomes": {
            "INTERESTED": "TASK_RENT_PREPARE_TENANCY",
            "NEEDS_ANOTHER_UNIT": "TASK_RENT_MATCH_PROPERTIES",
            "NOT_INTERESTED": None,
            "NO_SHOW": "TASK_VIEWING_RESCHEDULE"
        }
    },
    "TASK_RENT_SPECIAL_CONDITIONS_NEGOTIATION": {
        "next": "TASK_RENT_PREPARE_TENANCY",
        "outcomes": {
            "CONDITIONS_AGREED": "TASK_RENT_PREPARE_TENANCY",
            "REJECTED": "TASK_RENT_MATCH_PROPERTIES"
        }
    },
    "TASK_RENT_PREPARE_TENANCY": {
        "next": "TASK_RENT_COLLECTION_MONITORING",
        "outcomes": {
            "EXECUTED": "TASK_RENT_COLLECTION_MONITORING",
            "AGREEMENT_EXECUTED": "TASK_RENT_COLLECTION_MONITORING",
            "APPROVED": "TASK_RENT_COLLECTION_MONITORING",
            "REJECTED": "TASK_RENT_MATCH_PROPERTIES",
            "TERMS_REJECTED": "TASK_RENT_MATCH_PROPERTIES"
        }
    },
    "TASK_RENT_COLLECTION_MONITORING": {
        "next": None,  # Terminal Task: Ongoing active tenancy monitoring
        "outcomes": None
    },
    "TASK_RENT_TENANT_SCREENING_CREDIT": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_RENT_COMMERCIAL_LICENSING_CHECK": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_RENT_SECURITY_DEPOSIT_RECEIPT": {
        "next": "TASK_RENT_COLLECTION_MONITORING",
        "outcomes": {
            "RECEIVED": "TASK_RENT_COLLECTION_MONITORING"
        }
    },

    # -------------------------------------------------------------------------
    # 4. Investment Pipeline
    # -------------------------------------------------------------------------
    "TASK_INVEST_CONFIRM_OBJECTIVES": {
        "next": "TASK_INVEST_COMPARE_RETURNS",
        "outcomes": None
    },
    "TASK_INVEST_COMPARE_RETURNS": {
        "next": "TASK_INVEST_SCHEDULE_INSPECTION",
        "outcomes": {
            "NO_SUITABLE_UNITS": None
        }
    },
    "TASK_INVEST_SCHEDULE_INSPECTION": {
        "next": "TASK_INVEST_INSPECTION_REPORT",
        "outcomes": {
            "CANCELLED": None
        }
    },
    "TASK_INVEST_INSPECTION_REPORT": {
        "next": "TASK_INVEST_VALIDATE_FINANCIALS",
        "outcomes": {
            "RECOMMENDED": "TASK_INVEST_VALIDATE_FINANCIALS",
            "COMPLETED": "TASK_INVEST_VALIDATE_FINANCIALS",
            "REJECTED": "TASK_INVEST_COMPARE_RETURNS",
            "NOT_RECOMMENDED": "TASK_INVEST_COMPARE_RETURNS"
        }
    },
    "TASK_INVEST_VALIDATE_FINANCIALS": {
        "next": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
        "outcomes": {
            "VALIDATED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "APPROVED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "DISCOUNT_REQUIRED": "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
            "REJECTED": "TASK_INVEST_COMPARE_RETURNS"
        }
    },
    "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT": {
        "next": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
        "outcomes": {
            "DISCOUNT_ACCEPTED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "COMPROMISE_AGREED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "DISCOUNT_REJECTED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "NEGOTIATION_FAILED": "TASK_INVEST_COMPARE_RETURNS"
        }
    },
    "TASK_INVEST_PREPARE_ACQUISITION_OFFER": {
        "next": "TASK_INVEST_BASELINE_PERFORMANCE",
        "outcomes": {
            "OFFER_ACCEPTED": "TASK_INVEST_BASELINE_PERFORMANCE",
            "OFFER_COMPROMISE": "TASK_INVEST_BASELINE_PERFORMANCE",
            "ACCEPTED": "TASK_INVEST_BASELINE_PERFORMANCE",
            "WON": "TASK_INVEST_BASELINE_PERFORMANCE",
            "OFFER_REJECTED": "TASK_INVEST_COMPARE_RETURNS",
            "REJECTED": "TASK_INVEST_COMPARE_RETURNS"
        }
    },
    "TASK_INVEST_BASELINE_PERFORMANCE": {
        "next": "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
        "outcomes": None
    },
    "TASK_INVEST_MONITOR_ACTUAL_RETURNS": {
        "next": "TASK_INVEST_PORTFOLIO_REVIEW",
        "outcomes": None
    },
    "TASK_INVEST_PORTFOLIO_REVIEW": {
        "next": None,  # Terminal / Periodic review loop
        "outcomes": {
            "HOLD": "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
            "MONITOR_AGAIN": "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
            "LIQUIDATE": None,
            "EXIT": None
        }
    },
    "TASK_INVEST_LEGAL_TITLE_AUDIT": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_INVEST_TAX_ZAKAT_ADVISORY": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_INVEST_TAQEEM_VALUATION": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },
    "TASK_INVEST_ENVIRONMENTAL_SOIL_CHECK": {
        "next": None,  # Standalone Consultative Task
        "outcomes": None
    },

    # -------------------------------------------------------------------------
    # 5. Financial / Accounting Terminal Tasks
    # -------------------------------------------------------------------------
    "TASK_COLLECT_SAUDI_FEES": {
        "next": None,  # Terminal Task
        "outcomes": None
    },
    "TASK_COMMISSION_SETTLEMENT": {
        "next": None,  # Terminal Task
        "outcomes": None
    },
    "TASK_CONTRACT_RECONCILIATION": {
        "next": None,  # Terminal Task
        "outcomes": None
    }
}


async def run_migration():
    print("Connecting to PostgreSQL...")
    conn = await asyncpg.connect(
        user="postgres",
        password="fAlnemari@1392",
        host="127.0.0.1",
        port=5432,
        database="re_db"
    )

    try:
        # 1. Add columns to workflow_templates
        print("Adding 'next_template_id' and 'outcome_transitions' columns...")
        await conn.execute("""
            ALTER TABLE workflow_templates
            ADD COLUMN IF NOT EXISTS next_template_id VARCHAR(100) REFERENCES workflow_templates(template_id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS outcome_transitions JSONB DEFAULT NULL;
        """)
        print("Columns created successfully.")

        # 2. Seed transitions for each template in TRANSITIONS_CATALOG
        print(f"Updating transitions for {len(TRANSITIONS_CATALOG)} TASK templates...")
        updated_count = 0
        for tid, conf in TRANSITIONS_CATALOG.items():
            next_tid = conf["next"]
            outcomes_json = json.dumps(conf["outcomes"], ensure_ascii=False) if conf["outcomes"] else None

            # Verify that template exists
            exists = await conn.fetchval("SELECT 1 FROM workflow_templates WHERE template_id = $1", tid)
            if not exists:
                print(f"  WARNING: Template '{tid}' not found in database! Skipping.")
                continue

            # Verify next_template_id if provided
            if next_tid:
                next_exists = await conn.fetchval("SELECT 1 FROM workflow_templates WHERE template_id = $1", next_tid)
                if not next_exists:
                    print(f"  ERROR: Next template '{next_tid}' referenced by '{tid}' does not exist! Setting to NULL.")
                    next_tid = None

            await conn.execute("""
                UPDATE workflow_templates
                SET next_template_id = $1,
                    outcome_transitions = $2::jsonb
                WHERE template_id = $3;
            """, next_tid, outcomes_json, tid)
            updated_count += 1

        print(f"Successfully updated transitions for {updated_count} templates.")

        # 3. Analyze Entry, Intermediate, Terminal, and Standalone Tasks
        all_tasks = await conn.fetch("""
            SELECT template_id, standard_title_ar, next_template_id, outcome_transitions
            FROM workflow_templates
            WHERE template_type = 'TASK'
            ORDER BY template_id;
        """)

        # Calculate in-degree (who points to this task)
        in_degree = {t["template_id"]: 0 for t in all_tasks}
        for t in all_tasks:
            if t["next_template_id"] and t["next_template_id"] in in_degree:
                in_degree[t["next_template_id"]] += 1
            if t["outcome_transitions"]:
                outcomes = json.loads(t["outcome_transitions"])
                for out_k, target_t in outcomes.items():
                    if target_t and target_t in in_degree:
                        in_degree[target_t] += 1

        entry_tasks = []
        terminal_tasks = []
        intermediate_tasks = []

        for t in all_tasks:
            tid = t["template_id"]
            has_incoming = in_degree[tid] > 0
            has_outgoing = bool(t["next_template_id"]) or bool(t["outcome_transitions"])

            if not has_incoming:
                entry_tasks.append(t)
            if not has_outgoing:
                terminal_tasks.append(t)
            if has_incoming and has_outgoing:
                intermediate_tasks.append(t)

        print("\n" + "="*80)
        print("WORKFLOW TOPOLOGY VERIFICATION SUMMARY:")
        print("="*80)
        print(f"Total TASK templates: {len(all_tasks)}")
        print(f"Entry / Root Tasks (No preceding tasks) [Count: {len(entry_tasks)}]:")
        for et in entry_tasks:
            print(f"  - [{et['template_id']}] -> Next: {et['next_template_id']} | Title: {et['standard_title_ar']}")

        print(f"\nTerminal / Leaf Tasks (No succeeding tasks) [Count: {len(terminal_tasks)}]:")
        for tt in terminal_tasks:
            print(f"  - [{tt['template_id']}] (Incoming references: {in_degree[tt['template_id']]}) | Title: {tt['standard_title_ar']}")

        print(f"\nIntermediate Tasks (Have incoming and outgoing) [Count: {len(intermediate_tasks)}]:")
        for it in intermediate_tasks:
            print(f"  - [{it['template_id']}] -> Next: {it['next_template_id']}")

        print("="*80)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
