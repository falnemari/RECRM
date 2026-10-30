import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta, date

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.schemas.management import TenancyCreateIn, RentCollectionPaymentIn
from app.routers.management import create_tenancy, record_rent_payment


class TestRentalWorkflow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN', 'LEASING_AGENT') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

        # Create or fetch a test customer
        self.test_customer_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=self.conn,
            org_id=self.org_id,
            first_name="Faisal",
            last_name="Al-Mutairi",
            mobile="+966509988776",
            email="faisal.rent@example.com"
        )

        # Dedicated Isolated Test Unit (Never borrow live inventory units)
        bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"
        self.test_unit_id = "unit-rent-test-01"
        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id,
                unit_number, floor_no, bedrooms, bathrooms, area_sqm,
                rent_price, status, created_at, updated_at
            ) VALUES ($1, $2, $3, 'R-101', 1, 2, 2, 95.0, 42000, 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', rent_price = 42000
            """,
            self.test_unit_id, bld_id, pt_id
        )

    async def asyncTearDown(self):
        # Reset test unit status to AVAILABLE if modified
        if hasattr(self, "test_unit_id"):
            await self.conn.execute("UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", self.test_unit_id)
            await self.conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE unit_id = $1)", self.test_unit_id)
            await self.conn.execute("DELETE FROM documents WHERE unit_id = $1", self.test_unit_id)
        if hasattr(self, "test_customer_id"):
            await self.conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE customer_id = $1)", self.test_customer_id)
            await self.conn.execute("DELETE FROM documents WHERE customer_id = $1", self.test_customer_id)
        await self.conn.close()

    async def test_01_rental_lead_creation_and_first_contact(self):
        """
        1. When an inbound lead with inquiry_type='RENT' is created and assigned:
           - Automatically spawns TASK_RENT_LEAD_FIRST_CONTACT with 30-minute SLA.
           - Records ACT_LEAD_ASSIGNED.
        """
        lead_id = f"lead-rent-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'HIGH', 'RENT', 30000, 50000, NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        res = await WorkflowEngine.on_lead_assigned(
            conn=self.conn,
            lead_id=lead_id,
            assigned_user_id=self.agent_id
        )

        self.assertIn("task", res)
        task = res["task"]
        self.assertEqual(task["template_id"], "TASK_RENT_LEAD_FIRST_CONTACT")
        self.assertEqual(task["status"], "PENDING")
        self.assertEqual(task["priority"], "HIGH")

        # Verify SLA is within 30 minutes
        due_at = task["due_at"]
        now = datetime.now(timezone.utc)
        time_diff = (due_at - now).total_seconds() / 60
        self.assertGreater(time_diff, 20)
        self.assertLessEqual(time_diff, 31)

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_02_rental_first_contact_outcome_and_qualification(self):
        """
        2. First Contact Outcome:
           - Completing TASK_RENT_LEAD_FIRST_CONTACT with outcome='QUALIFIED'
           - Advances lead status to 'QUALIFIED'
           - Creates opportunity in stage 'QUALIFIED'
           - Records ACT_RENT_LEAD_QUALIFIED activity
           - Automatically spawns TASK_RENT_MATCH_PROPERTIES with 24h SLA.
        """
        lead_id = f"lead-rent-q-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'ASSIGNED', 'HIGH', 'RENT', 35000, 48000, NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        # Spawn initial contact task
        task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_RENT_LEAD_FIRST_CONTACT",
            lead_id=lead_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id,
            priority="HIGH"
        )

        # Complete task with QUALIFIED outcome
        comp_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=task["task_id"],
            user_id=self.agent_id,
            outcome="QUALIFIED",
            notes="تم استيفاء ميزانية الإيجار وتفضيلات الموقع وتاريخ الانتقال.",
            qualification_data={"budget_min": 36000, "budget_max": 45000}
        )

        # Verify task is completed
        t_row = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", task["task_id"])
        self.assertEqual(t_row["status"], "COMPLETED")

        # Verify lead status is QUALIFIED
        l_row = await self.conn.fetchrow("SELECT status, budget_max FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(l_row["status"], "QUALIFIED")
        self.assertEqual(float(l_row["budget_max"]), 45000.0)

        # Verify opportunity created in QUALIFIED stage
        opp = await self.conn.fetchrow("SELECT opportunity_id, stage FROM opportunities WHERE lead_id = $1", lead_id)
        self.assertIsNotNone(opp)
        self.assertEqual(opp["stage"], "QUALIFIED")

        # Verify activity ACT_RENT_LEAD_QUALIFIED was recorded
        act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE lead_id = $1 AND template_id = 'ACT_RENT_LEAD_QUALIFIED'",
            lead_id
        )
        self.assertIsNotNone(act)
        self.assertEqual(act["outcome"], "QUALIFIED")

        # Verify next task is TASK_RENT_MATCH_PROPERTIES with 24h SLA
        match_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_RENT_MATCH_PROPERTIES'",
            lead_id
        )
        self.assertIsNotNone(match_task)
        self.assertEqual(match_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_03_rental_matching_and_presentation(self):
        """
        3. Property Matching:
           - Presenting matched units completes TASK_RENT_MATCH_PROPERTIES
           - Records ACT_RENT_PROPERTIES_MATCHED activity
           - Automatically spawns TASK_RENT_VIEWING_FOLLOW_UP.
        """
        lead_id = f"lead-rent-m-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'RENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        opp_id = f"opp-rent-m-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 42000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        match_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_RENT_MATCH_PROPERTIES",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id,
            priority="HIGH"
        )

        # Complete matching task
        comp_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=match_task["task_id"],
            user_id=self.agent_id,
            outcome="PRESENTED",
            notes="تم ترشيح الوحدة المختارة ومشاركتها مع العميل عبر الواتساب.",
            viewing_data={"unit_ids": [self.test_unit_id]}
        )

        # Verify task completed
        t_row = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", match_task["task_id"])
        self.assertEqual(t_row["status"], "COMPLETED")

        # Verify activity ACT_RENT_PROPERTIES_MATCHED logged
        act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_RENT_PROPERTIES_MATCHED'",
            opp_id
        )
        self.assertIsNotNone(act)

        # Verify next task is TASK_VIEWING_SCHEDULE
        schedule_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_SCHEDULE'",
            opp_id
        )
        self.assertIsNotNone(schedule_task)
        self.assertEqual(schedule_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_04_viewing_outcome_interested_diverges_to_tenancy_prep(self):
        """
        4. Viewing Outcome Divergence:
           - Rental Lead with viewing report outcome='INTERESTED'
           - Must route to TASK_RENT_PREPARE_TENANCY (48h SLA)
           - Must NOT route to TASK_OFFER_SUBMIT (which is for buying).
        """
        lead_id = f"lead-rent-v-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'RENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        opp_id = f"opp-rent-v-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'VIEWING', 42000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        # Schedule viewing
        sch_res = await WorkflowEngine.schedule_property_viewing(
            conn=self.conn,
            user_id=self.agent_id,
            unit_id=self.test_unit_id,
            scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id
        )
        report_task = sch_res["report_task"]

        # Complete viewing report with outcome INTERESTED
        report_res = await WorkflowEngine.complete_property_viewing_report(
            conn=self.conn,
            task_id=report_task["task_id"],
            user_id=self.agent_id,
            outcome="INTERESTED",
            feedback_notes="العميل وافق على الوحدة ويرغب في استئجارها سنوياً."
        )

        # Verify next action spawned TASK_RENT_PREPARE_TENANCY (NOT TASK_OFFER_SUBMIT!)
        self.assertEqual(report_res["next_action"]["type"], "TENANCY_PREPARATION_SPAWNED")
        tenancy_task = report_res["next_action"]["task"]
        self.assertEqual(tenancy_task["template_id"], "TASK_RENT_PREPARE_TENANCY")

        # Verify offer task was NOT spawned
        offer_task = await self.conn.fetchrow(
            "SELECT task_id FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_OFFER_SUBMIT'",
            opp_id
        )
        self.assertIsNone(offer_task, "Rental workflow must NEVER spawn purchase TASK_OFFER_SUBMIT")

        # Cleanup
        await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM viewings WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_05_viewing_outcome_not_interested_non_destructive(self):
        """
        5. Non-Destructive Rematching:
           - Viewing report with outcome='NOT_INTERESTED' on a rental lead
           - Re-routes to TASK_RENT_MATCH_PROPERTIES to find alternative units
           - Does NOT close or disqualify the lead.
        """
        lead_id = f"lead-rent-nd-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'RENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        opp_id = f"opp-rent-nd-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'VIEWING', 42000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        sch_res = await WorkflowEngine.schedule_property_viewing(
            conn=self.conn,
            user_id=self.agent_id,
            unit_id=self.test_unit_id,
            scheduled_start=datetime.now(timezone.utc) + timedelta(hours=2),
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id
        )
        report_task = sch_res["report_task"]

        # Complete with NOT_INTERESTED
        report_res = await WorkflowEngine.complete_property_viewing_report(
            conn=self.conn,
            task_id=report_task["task_id"],
            user_id=self.agent_id,
            outcome="NOT_INTERESTED",
            feedback_notes="المساحة صغيرة ويرغب في 3 غرف بدلاً من غرفتين."
        )

        # Must spawn TASK_RENT_MATCH_PROPERTIES
        self.assertEqual(report_res["next_action"]["type"], "RENT_MATCH_SPAWNED")
        self.assertEqual(report_res["next_action"]["task"]["template_id"], "TASK_RENT_MATCH_PROPERTIES")

        # Lead must still be QUALIFIED (not closed!)
        lead_row = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_row["status"], "QUALIFIED")

        # Cleanup
        await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM viewings WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_06_tenancy_agreement_execution_and_rent_collections(self):
        """
        6. Full Tenancy Execution Gateway:
           - Atomic execution of tenancy contract
           - Unit status updates to 'RENTED'
           - Installments generated in rent_collections table
           - TASK_RENT_PREPARE_TENANCY completed
           - Spawns recurring TASK_RENT_COLLECTION_MONITORING
           - Activity ACT_TENANCY_ACTIVATED logged
           - Opportunity and Lead stage/status advance to 'WON'.
        """
        lead_id = f"lead-rent-exec-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'RENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        opp_id = f"opp-rent-exec-{int(datetime.now(timezone.utc).timestamp())}"
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEGOTIATION', 42000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        prep_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_RENT_PREPARE_TENANCY",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id,
            priority="HIGH"
        )

        # Execute Tenancy Agreement
        start_d = date.today()
        end_d = start_d + timedelta(days=365)
        exec_res = await WorkflowEngine.execute_tenancy_agreement(
            conn=self.conn,
            unit_id=self.test_unit_id,
            tenant_customer_id=self.test_customer_id,
            start_date=start_d,
            end_date=end_d,
            rent_amount=48000.0,
            payment_frequency="QUARTERLY",
            deposit_amount=5000.0,
            contract_number=f"TEN-TEST-{int(datetime.now(timezone.utc).timestamp())}",
            lead_id=lead_id,
            opportunity_id=opp_id,
            user_id=self.agent_id,
            generate_installments=True,
            installments_count=4,
            parent_task_id=prep_task["task_id"]
        )

        tenancy_id = exec_res["tenancy_id"]
        self.assertIsNotNone(tenancy_id)

        # 1. Tenancy record created
        t_row = await self.conn.fetchrow("SELECT * FROM tenancies WHERE tenancy_id = $1", tenancy_id)
        self.assertEqual(t_row["status"], "ACTIVE")
        self.assertEqual(float(t_row["rent_amount"]), 48000.0)

        # 2. Unit status atomically updated to RENTED
        u_row = await self.conn.fetchrow("SELECT status FROM units WHERE unit_id = $1", self.test_unit_id)
        self.assertEqual(u_row["status"], "RENTED")

        # 3. Exactly 4 installments generated in rent_collections
        rc_rows = await self.conn.fetch(
            "SELECT * FROM rent_collections WHERE tenancy_id = $1 ORDER BY due_date ASC",
            tenancy_id
        )
        self.assertEqual(len(rc_rows), 4)
        for r in rc_rows:
            self.assertEqual(float(r["amount_due"]), 12000.0)
            self.assertEqual(float(r["amount_paid"]), 0.0)
            self.assertEqual(r["status"], "DUE")

        # 4. TASK_RENT_PREPARE_TENANCY completed
        prep_db = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", prep_task["task_id"])
        self.assertEqual(prep_db["status"], "COMPLETED")

        # 5. Monitoring task spawned
        mon_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_RENT_COLLECTION_MONITORING'",
            opp_id
        )
        self.assertIsNotNone(mon_task)

        # 6. Activity ACT_TENANCY_ACTIVATED recorded
        act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_TENANCY_ACTIVATED'",
            opp_id
        )
        self.assertIsNotNone(act)
        self.assertEqual(act["outcome"], "ACTIVE")

        # 7. Lead and Opportunity stages set to WON
        opp_db = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_db["stage"], "WON")
        lead_db = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_db["status"], "WON")

        # 8. Record payment on installment 1
        first_rc = rc_rows[0]
        pay_res = await record_rent_payment(
            rent_collection_id=first_rc["rent_collection_id"],
            payload=RentCollectionPaymentIn(amount_paid=12000.0),
            x_user_id=self.agent_id,
            conn=self.conn
        )
        self.assertEqual(pay_res.data.status, "PAID")
        self.assertEqual(pay_res.data.amount_paid, 12000.0)

        # Verify activity ACT_RENT_PAYMENT_COLLECTED logged
        pay_act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE customer_id = $1 AND template_id = 'ACT_RENT_PAYMENT_COLLECTED' ORDER BY created_at DESC LIMIT 1",
            self.test_customer_id
        )
        self.assertIsNotNone(pay_act)
        self.assertEqual(pay_act["outcome"], "PAID")

        # 9. Concurrency / Double-lease test: attempting to lease this now-RENTED unit must fail
        with self.assertRaises(ValueError):
            await WorkflowEngine.execute_tenancy_agreement(
                conn=self.conn,
                unit_id=self.test_unit_id,
                tenant_customer_id=self.test_customer_id,
                start_date=start_d,
                rent_amount=48000.0
            )

        # 10. Verify LEASE Contract Document was automatically archived in documents table
        lease_doc = await self.conn.fetchrow(
            """
            SELECT d.*, dt.code AS doc_code
            FROM documents d
            JOIN document_types dt ON d.document_type_id = dt.document_type_id
            WHERE dt.code = 'LEASE' AND (d.lead_id = $1 OR d.opportunity_id = $2)
            """,
            lead_id, opp_id
        )
        self.assertIsNotNone(lease_doc, "Official Lease Agreement document must be archived in documents table")
        self.assertIn("عقد_إيجار_موحد_موثق", lease_doc["file_name"])

        # 11. Verify TASK_RENT_COLLECTION_MONITORING is assigned to an ACCOUNTANT user
        mon_task = await self.conn.fetchrow(
            """
            SELECT t.*, r.role_code
            FROM tasks t
            LEFT JOIN users u ON t.assigned_user_id = u.user_id
            LEFT JOIN user_roles ur ON u.user_id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.role_id
            WHERE t.template_id = 'TASK_RENT_COLLECTION_MONITORING' AND (t.lead_id = $1 OR t.opportunity_id = $2)
            """,
            lead_id, opp_id
        )
        self.assertIsNotNone(mon_task, "Monitoring task must be created")
        self.assertIn(mon_task["role_code"], ("ACCOUNTANT", "FINANCE"))

        # Cleanup
        await self.conn.execute("DELETE FROM documents WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
        await self.conn.execute("DELETE FROM rent_collections WHERE tenancy_id = $1", tenancy_id)
        await self.conn.execute("DELETE FROM tenancies WHERE tenancy_id = $1", tenancy_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", self.test_unit_id)


if __name__ == "__main__":
    unittest.main()
