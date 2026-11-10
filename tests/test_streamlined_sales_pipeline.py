import pytest
import asyncpg
from datetime import datetime, timezone, timedelta
from app.services.workflow_engine import WorkflowEngine

@pytest.mark.asyncio
async def test_streamlined_sales_pipeline_end_to_end():
    conn = await asyncpg.connect("postgresql://postgres:fAlnemari%401392@localhost:5432/redb")
    
    try:
        # 1. Verify templates exist in workflow_templates
        templates = await conn.fetch("""
            SELECT template_id, standard_title_ar, next_template_id, outcome_transitions
            FROM workflow_templates
            WHERE template_id IN ('TASK_SALES_LEAD_CONTACT_QUALIFY', 'TASK_LEAD_FOLLOWUP_QUALIFY', 'TASK_MATCH_PROPERTIES')
        """)
        found_ids = {t["template_id"] for t in templates}
        assert "TASK_SALES_LEAD_CONTACT_QUALIFY" in found_ids
        assert "TASK_LEAD_FOLLOWUP_QUALIFY" in found_ids
        assert "TASK_MATCH_PROPERTIES" in found_ids

        import json
        tmpl_map = {t["template_id"]: (json.loads(t["outcome_transitions"]) if isinstance(t["outcome_transitions"], str) else t["outcome_transitions"]) for t in templates}
        assert list(tmpl_map["TASK_SALES_LEAD_CONTACT_QUALIFY"].keys()) == [
            "CONTACTED_QUALIFIED", "CALLBACK_REQUESTED", "UNREACHABLE", "NOT_INTERESTED", "INVALID_CONTACT"
        ]
        assert list(tmpl_map["TASK_LEAD_FOLLOWUP_QUALIFY"].keys()) == [
            "CONTACTED_QUALIFIED", "CALLBACK_REQUESTED", "UNREACHABLE", "NOT_INTERESTED"
        ]

        # 2. Verify next_template resolution for TASK_LEAD_ASSIGN with outcome SALES
        next_tmpl = await WorkflowEngine.resolve_next_task_template(conn, "TASK_LEAD_ASSIGN", "SALES")
        assert next_tmpl == "TASK_SALES_LEAD_CONTACT_QUALIFY"

        # 3. Create a test lead
        org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "organization-1"
        cust_id = await conn.fetchval("SELECT customer_id FROM customers LIMIT 1") or "customer-1"
        agent_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1") or "user-51"

        lead_id = "test-lead-streamlined-" + str(int(datetime.now().timestamp()))
        await conn.execute("""
            INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, created_at, updated_at)
            VALUES ($1, $2, $3, 'BUY', 'NEW', 'HIGH', NOW(), NOW())
        """, lead_id, org_id, cust_id)

        # 4. Spawn TASK_SALES_LEAD_CONTACT_QUALIFY
        contact_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_SALES_LEAD_CONTACT_QUALIFY",
            lead_id=lead_id,
            customer_id=cust_id,
            assigned_user_id=agent_id,
            priority="HIGH"
        )
        assert contact_task is not None
        assert contact_task["template_id"] == "TASK_SALES_LEAD_CONTACT_QUALIFY"

        # 5. Complete with CONTACTED_QUALIFIED (testing alias and normalization)
        complete_res = await WorkflowEngine.complete_task_with_outcome(
            conn=conn,
            task_id=contact_task["task_id"],
            user_id=agent_id,
            outcome="CONTACTED & QUALIFIED",
            notes="عميل مؤهل ومهتم بشراء فيلا شمال الرياض",
            qualification_data={
                "budget_min": 2500000,
                "budget_max": 3500000
            }
        )
        assert complete_res["status"] == "COMPLETED"
        assert complete_res["business_transition"]["status"] == "QUALIFIED"

        # Verify lead status & first_contact_at
        lead_row = await conn.fetchrow("SELECT status, first_contact_at, budget_min, budget_max FROM leads WHERE lead_id = $1", lead_id)
        assert lead_row["status"] == "QUALIFIED"
        assert lead_row["first_contact_at"] is not None
        assert float(lead_row["budget_min"]) == 2500000.0

        # Verify next task is TASK_MATCH_PROPERTIES
        next_task = complete_res["business_transition"]["matching_task"]
        assert next_task is not None
        assert next_task["template_id"] == "TASK_MATCH_PROPERTIES"

        # 6. Complete TASK_MATCH_PROPERTIES
        unit_id = await conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1") or "unit-1"
        match_res = await WorkflowEngine.complete_task_with_outcome(
            conn=conn,
            task_id=next_task["task_id"],
            user_id=agent_id,
            outcome="MATCHED",
            notes="تم ترشيح الوحدات المطابقة",
            viewing_data={"unit_ids": [unit_id]}
        )
        assert match_res["status"] == "COMPLETED"
        assert match_res["viewing_task"] is not None
        assert match_res["viewing_task"]["template_id"] == "TASK_VIEWING_SCHEDULE"

        # Cleanup
        await conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", complete_res["business_transition"]["opportunity_id"])
        await conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_streamlined_unreachable_retry_and_terminal():
    conn = await asyncpg.connect("postgresql://postgres:fAlnemari%401392@localhost:5432/redb")
    
    try:
        org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "organization-1"
        cust_id = await conn.fetchval("SELECT customer_id FROM customers LIMIT 1") or "customer-1"
        agent_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1") or "user-51"

        lead_id = "test-lead-unreachable-" + str(int(datetime.now().timestamp()))
        await conn.execute("""
            INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, created_at, updated_at)
            VALUES ($1, $2, $3, 'BUY', 'ASSIGNED', 'HIGH', NOW(), NOW())
        """, lead_id, org_id, cust_id)

        # 1. Attempt 1 on TASK_SALES_LEAD_CONTACT_QUALIFY: UNREACHABLE
        task1, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_SALES_LEAD_CONTACT_QUALIFY",
            lead_id=lead_id,
            customer_id=cust_id,
            assigned_user_id=agent_id
        )
        res1 = await WorkflowEngine.complete_task_with_outcome(
            conn=conn,
            task_id=task1["task_id"],
            user_id=agent_id,
            outcome="UNREACHABLE",
            notes="لم يرد العميل - المحاولة الأولى"
        )
        # Should record first_contact_at and spawn follow-up 1
        lead_after_1 = await conn.fetchrow("SELECT first_contact_at FROM leads WHERE lead_id = $1", lead_id)
        assert lead_after_1["first_contact_at"] is not None
        task2 = res1["business_transition"]["followup_task"]
        assert task2["template_id"] == "TASK_LEAD_FOLLOWUP_QUALIFY"
        assert task2["retry_count"] == 1

        # 2. Attempt 2 on TASK_LEAD_FOLLOWUP_QUALIFY: UNREACHABLE
        res2 = await WorkflowEngine.complete_task_with_outcome(
            conn=conn,
            task_id=task2["task_id"],
            user_id=agent_id,
            outcome="UNREACHABLE",
            notes="لم يرد العميل - المحاولة الثانية"
        )
        task3 = res2["business_transition"]["followup_task"]
        assert task3["template_id"] == "TASK_LEAD_FOLLOWUP_QUALIFY"
        assert task3["retry_count"] == 2

        # 3. Attempt 3 on TASK_LEAD_FOLLOWUP_QUALIFY: UNREACHABLE (ceiling reached!)
        res3 = await WorkflowEngine.complete_task_with_outcome(
            conn=conn,
            task_id=task3["task_id"],
            user_id=agent_id,
            outcome="UNREACHABLE",
            notes="لم يرد العميل - المحاولة الثالثة والأخيرة"
        )
        assert res3["business_transition"]["max_retries_exceeded"] is True
        assert res3["business_transition"]["new_status"] == "UNREACHABLE"

        # Verify lead status is terminal UNREACHABLE
        lead_after_3 = await conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        assert lead_after_3 == "UNREACHABLE"

        # Cleanup
        await conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    finally:
        await conn.close()
