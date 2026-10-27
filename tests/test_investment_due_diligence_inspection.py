import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.services.workflow_engine import WorkflowEngine


class TestInvestmentDueDiligenceInspection(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME
        )
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('INVESTMENT_ADVISOR', 'SALES_AGENT', 'SYS_ADMIN') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

        # Customer
        self.test_customer_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=self.conn,
            org_id=self.org_id,
            first_name="Tariq",
            last_name="Al-Ghamdi",
            mobile="+966501122334",
            email="tariq.invest@example.com"
        )

        # Dedicated Isolated Test Unit (Never borrow live inventory units)
        bld = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"
        self.test_unit_id = "unit-test-inv-ddr"
        await self.conn.execute(
            """
            INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, rent_price, status, created_at, updated_at)
            VALUES ($1, $2, 'INV-DDR-101', $3, 2500000.0, 200000.0, 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', owner_customer_id = NULL, asking_price = 2500000.0, rent_price = 200000.0, updated_at = NOW()
            """,
            self.test_unit_id, bld, pt
        )

    async def asyncTearDown(self):
        if hasattr(self, "test_unit_id"):
            await self.conn.execute("UPDATE units SET status = 'AVAILABLE', owner_customer_id = NULL WHERE unit_id = $1", self.test_unit_id)
        await self.conn.close()

    async def test_01_compare_returns_spawns_due_diligence_inspection_schedule(self):
        """
        1. Compare Property Returns must now spawn TASK_INVEST_SCHEDULE_INSPECTION
           instead of skipping directly to financial validation.
        """
        lead_id = f"lead-inv-dd-{int(datetime.now(timezone.utc).timestamp())}"
        opp_id = f"opp-inv-dd-{int(datetime.now(timezone.utc).timestamp())}"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 2500000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        comp_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_COMPARE_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete returns comparison
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=comp_task["task_id"],
            user_id=self.agent_id,
            outcome="RETURNS_COMPARED",
            viewing_data={
                "unit_id": self.test_unit_id,
                "purchase_price": 2500000.0,
                "monthly_rent_forecast": 18000.0,
                "annual_vacancy_allowance": 10000.0,
                "annual_operating_expenses": 12000.0,
                "acquisition_costs": 125000.0
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_RETURNS_COMPARED")

        # Verify next task is TASK_INVEST_SCHEDULE_INSPECTION
        sched_task = await self.conn.fetchrow(
            "SELECT task_id, template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_SCHEDULE_INSPECTION'",
            opp_id
        )
        self.assertIsNotNone(sched_task, "Completing return comparisons must spawn TASK_INVEST_SCHEDULE_INSPECTION")
        self.assertEqual(sched_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_02_schedule_inspection_triggers_comm_activity_and_report_task(self):
        """
        2. Scheduling investment inspection must complete scheduling task,
           log ACT_INVEST_INSPECTION_SCHEDULED, send COMM_INVEST_INSPECTION_CONFIRMATION,
           and auto-spawn TASK_INVEST_INSPECTION_REPORT.
        """
        lead_id = f"lead-inv-sch-{int(datetime.now(timezone.utc).timestamp())}"
        opp_id = f"opp-inv-sch-{int(datetime.now(timezone.utc).timestamp())}"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 2500000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        sched_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_SCHEDULE_INSPECTION",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        sch_start = datetime.now(timezone.utc) + timedelta(days=2, hours=10)
        sch_res = await WorkflowEngine.schedule_property_viewing(
            conn=self.conn,
            user_id=self.agent_id,
            unit_id=self.test_unit_id,
            scheduled_start=sch_start,
            task_id=sched_task["task_id"],
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            notes="فحص هندسي للمبنى ومحطة التكييف"
        )

        self.assertEqual(sch_res["status"], "SCHEDULED")

        # Verify scheduling task is COMPLETED
        t_status = await self.conn.fetchval("SELECT status FROM tasks WHERE task_id = $1", sched_task["task_id"])
        self.assertEqual(t_status, "COMPLETED")

        # Verify activity ACT_INVEST_INSPECTION_SCHEDULED
        act = await self.conn.fetchrow(
            "SELECT template_id, outcome, description FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_INVEST_INSPECTION_SCHEDULED'",
            opp_id
        )
        self.assertIsNotNone(act)
        self.assertIn("المعاينة والفحص الفني والاستثماري", act["description"])

        # Verify communication COMM_INVEST_INSPECTION_CONFIRMATION
        comm = await self.conn.fetchrow(
            "SELECT template_id, channel, delivery_status FROM communications WHERE lead_id = $1 AND template_id = 'COMM_INVEST_INSPECTION_CONFIRMATION'",
            lead_id
        )
        self.assertIsNotNone(comm)
        self.assertEqual(comm["delivery_status"], "SENT")

        # Verify spawned task is TASK_INVEST_INSPECTION_REPORT
        rep_task = sch_res["report_task"]
        self.assertEqual(rep_task["template_id"], "TASK_INVEST_INSPECTION_REPORT")
        self.assertEqual(rep_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM viewings WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_03_submit_detailed_due_diligence_report_and_db_storage(self):
        """
        3. Submitting TASK_INVEST_INSPECTION_REPORT must save full technical & commercial
           due diligence metrics to investment_due_diligence_reports and spawn TASK_INVEST_VALIDATE_FINANCIALS.
        """
        lead_id = f"lead-inv-rep-{int(datetime.now(timezone.utc).timestamp())}"
        opp_id = f"opp-inv-rep-{int(datetime.now(timezone.utc).timestamp())}"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'VIEWING', 2500000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        rep_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_INSPECTION_REPORT",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete with full Technical & Commercial Due Diligence details
        comp_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=rep_task["task_id"],
            user_id=self.agent_id,
            outcome="RECOMMENDED_WITH_PRICE_ADJUSTMENT",
            notes="تم فحص العقار، الهيكل الإنشائي سليم والمصاعد ممتازة، تم رصد حاجة لتجديد العزل ومضخات المياه بتكلفة CapEx 45,000 ريال. الإشغال 94% مطابق لمنصة إيجار.",
            viewing_data={
                "unit_id": self.test_unit_id,
                "structural_condition": "EXCELLENT",
                "building_age_years": 4,
                "saudi_building_code_compliant": True,
                "hvac_status": "OPERATIONAL",
                "elevators_status": "EXCELLENT",
                "plumbing_network_status": "GOOD",
                "electrical_network_status": "EXCELLENT",
                "roofing_and_insulation_status": "NEEDS_REPAIR",
                "fire_safety_compliance": "COMPLIANT",
                "estimated_capex_sar": 45000.0,
                "location_traffic_flow": "PRIME",
                "access_and_egress_quality": "EXCELLENT",
                "parking_availability": "ABUNDANT",
                "actual_occupancy_rate": 94.0,
                "total_units_inspected": 12,
                "occupied_units_count": 11,
                "vacant_units_count": 1,
                "rent_roll_verified": True,
                "property_manager_interview_notes": "المستأجرون منتظمون بالسداد عبر منصة إيجار.",
                "commercial_viability_score": 92,
                "recommendation": "RECOMMENDED_WITH_PRICE_ADJUSTMENT",
                "suggested_price_adjustment_sar": 45000.0,
                "final_verdict_summary": "العقار ممتاز كفرصة استثمارية مدرة مع التوصية بخصم 45 ألف ريال مقابل تجديد العزل."
            }
        )

        self.assertEqual(comp_res["status"], "COMPLETED")
        self.assertIn("business_transition", comp_res)
        b_trans = comp_res["business_transition"]
        self.assertEqual(b_trans["type"], "INVEST_INSPECTION_COMPLETED")
        report_id = b_trans["report_id"]
        self.assertIsNotNone(report_id)

        # Verify database record in investment_due_diligence_reports
        report_row = await self.conn.fetchrow(
            "SELECT * FROM investment_due_diligence_reports WHERE report_id = $1", report_id
        )
        self.assertIsNotNone(report_row)
        self.assertEqual(report_row["structural_condition"], "EXCELLENT")
        self.assertTrue(report_row["saudi_building_code_compliant"])
        self.assertEqual(float(report_row["estimated_capex_sar"]), 45000.0)
        self.assertEqual(float(report_row["actual_occupancy_rate"]), 94.0)
        self.assertTrue(report_row["rent_roll_verified"])
        self.assertEqual(report_row["recommendation"], "RECOMMENDED_WITH_PRICE_ADJUSTMENT")

        # Verify Financial Due Diligence Equations & Columns in Database
        self.assertGreater(float(report_row["purchase_price_sar"]), 0.0)
        self.assertGreater(float(report_row["gross_annual_rent_sar"]), 0.0)
        self.assertGreater(float(report_row["vacancy_allowance_sar"]), 0.0)
        self.assertGreater(float(report_row["operating_expenses_opex_sar"]), 0.0)
        self.assertGreater(float(report_row["net_operating_income_noi_sar"]), 0.0)
        self.assertGreater(float(report_row["total_investment_basis_sar"]), float(report_row["purchase_price_sar"]))
        self.assertGreater(float(report_row["cap_rate_percent"]), 0.0)
        self.assertGreater(float(report_row["net_yield_percent"]), 0.0)
        self.assertGreater(float(report_row["cash_on_cash_return_percent"]), 0.0)

        # Verify next task spawned is TASK_INVEST_VALIDATE_FINANCIALS
        val_task = await self.conn.fetchrow(
            "SELECT task_id, template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_VALIDATE_FINANCIALS'",
            opp_id
        )
        self.assertIsNotNone(val_task)
        self.assertEqual(val_task["status"], "PENDING")

        # Complete TASK_INVEST_VALIDATE_FINANCIALS and verify CapEx enrichment in notes
        val_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=val_task["task_id"],
            user_id=self.agent_id,
            outcome="VALIDATED"
        )
        self.assertEqual(val_res["status"], "COMPLETED")
        val_act = await self.conn.fetchrow(
            "SELECT description FROM activities WHERE task_id = $1 AND template_id = 'ACT_INVEST_FINANCIALS_VALIDATED'",
            val_task["task_id"]
        )
        self.assertIn("45,000", val_act["description"])
        self.assertIn("94", val_act["description"])

        # Test API endpoints with TestClient
        api_res = self.client.get(f"/api/v1/investment/reports/{report_id}")
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()["data"]
        self.assertEqual(data["report_id"], report_id)
        self.assertEqual(float(data["estimated_capex_sar"]), 45000.0)

        # Test HTML report endpoint
        html_res = self.client.get(f"/api/v1/investment/reports/{report_id}/html")
        self.assertEqual(html_res.status_code, 200)
        self.assertIn("تقرير الفحص الفني والاستثماري النافي للجهالة", html_res.text)
        self.assertIn("45,000", html_res.text)
        self.assertIn("الكود السعودي", html_res.text)
        self.assertIn("صافي الدخل التشغيلي (NOI)", html_res.text)
        self.assertIn("معدل الرسملة (Cap Rate)", html_res.text)
        self.assertIn("العائد على النقد المستثمر (Cash-on-Cash Return)", html_res.text)

        # Cleanup
        await self.conn.execute("DELETE FROM investment_due_diligence_reports WHERE report_id = $1", report_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_04_inspection_rejection_rematches_alternative_units(self):
        """
        4. When due diligence inspection outcome is REJECTED,
           it must non-destructively re-spawn TASK_INVEST_COMPARE_RETURNS.
        """
        lead_id = f"lead-inv-rej-{int(datetime.now(timezone.utc).timestamp())}"
        opp_id = f"opp-inv-rej-{int(datetime.now(timezone.utc).timestamp())}"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'VIEWING', 2500000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        rep_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_INSPECTION_REPORT",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        comp_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=rep_task["task_id"],
            user_id=self.agent_id,
            outcome="REJECTED",
            notes="تم رصد شروخ خطيرة في الأعمدة وتصدع بالهيكل الخرساني مع تسريب مياه جسيم بالأسطح. غير صالح للاستثمار.",
            viewing_data={
                "unit_id": self.test_unit_id,
                "structural_condition": "CRITICAL",
                "saudi_building_code_compliant": False,
                "recommendation": "REJECTED",
                "final_verdict_summary": "صرف النظر عن العقار لخطورة الحالة الإنشائية."
            }
        )

        self.assertEqual(comp_res["status"], "COMPLETED")
        self.assertEqual(comp_res["business_transition"]["type"], "INVEST_INSPECTION_REJECTED")

        # Verify next task is TASK_INVEST_COMPARE_RETURNS
        rematch_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_COMPARE_RETURNS'",
            opp_id
        )
        self.assertIsNotNone(rematch_task, "Rejection must non-destructively rematch alternative units")
        self.assertEqual(rematch_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE', owner_customer_id = NULL WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM investment_due_diligence_reports WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_05_due_diligence_to_baseline_and_monitoring_lifecycle(self):
        """
        5. Verify end-to-end integration:
           Due Diligence Report -> Baseline Performance -> Monitoring Actual Returns -> Portfolio Review.
           Ensure financial metrics (NOI, Cap Rate, Net Yield, CoC, Vacancy, OPEX) flow smoothly
           from the inspection report into all downstream lifecycle tasks.
        """
        lead_id = f"lead-inv-flow-{int(datetime.now(timezone.utc).timestamp())}"
        opp_id = f"opp-inv-flow-{int(datetime.now(timezone.utc).timestamp())}"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'NEGOTIATION', 3000000.0, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        # 1. Spawn and complete inspection report
        rep_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_INSPECTION_REPORT",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        rep_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=rep_task["task_id"],
            user_id=self.agent_id,
            outcome="RECOMMENDED",
            notes="معاينة فنية شاملة للمجمع الاستثماري.",
            viewing_data={
                "unit_id": self.test_unit_id,
                "purchase_price": 3000000.0,
                "gross_annual_rent": 240000.0,
                "actual_occupancy_rate": 90.0,
                "annual_operating_expenses": 20000.0,
                "estimated_capex_sar": 100000.0,
                "structural_condition": "GOOD",
                "saudi_building_code_compliant": True,
                "recommendation": "RECOMMENDED"
            }
        )
        self.assertEqual(rep_res["status"], "COMPLETED")
        report_id = rep_res["business_transition"]["report_id"]

        # Fetch saved due diligence report and verify financial equations
        dd_row = await self.conn.fetchrow("SELECT * FROM investment_due_diligence_reports WHERE report_id = $1", report_id)
        self.assertEqual(float(dd_row["purchase_price_sar"]), 3000000.0)
        self.assertEqual(float(dd_row["gross_annual_rent_sar"]), 240000.0)
        self.assertEqual(float(dd_row["vacancy_allowance_sar"]), 24000.0) # 10% of 240,000 based on 90% occupancy
        self.assertEqual(float(dd_row["operating_expenses_opex_sar"]), 20000.0)
        self.assertEqual(float(dd_row["net_operating_income_noi_sar"]), 196000.0) # 240,000 - 24,000 - 20,000
        self.assertEqual(float(dd_row["total_investment_basis_sar"]), 3100000.0) # 3,000,000 + 100,000 CapEx
        self.assertEqual(float(dd_row["cap_rate_percent"]), 6.53) # 196,000 / 3,000,000
        self.assertEqual(float(dd_row["net_yield_percent"]), 6.32) # 196,000 / 3,100,000

        # 2. Advance to offer won -> TASK_INVEST_BASELINE_PERFORMANCE
        base_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_BASELINE_PERFORMANCE",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete baseline task without manual overrides; it should automatically pull from dd_row
        base_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=base_task["task_id"],
            user_id=self.agent_id,
            outcome="BASELINE_ESTABLISHED"
        )
        self.assertEqual(base_res["status"], "COMPLETED")
        base_act = await self.conn.fetchrow(
            "SELECT description FROM activities WHERE task_id = $1 AND template_id = 'ACT_INVEST_BASELINE_ESTABLISHED'",
            base_task["task_id"]
        )
        self.assertIn(report_id, base_act["description"])
        self.assertIn("196,000", base_act["description"])
        self.assertIn("100,000", base_act["description"])

        # 3. Next task is TASK_INVEST_MONITOR_ACTUAL_RETURNS
        mon_task = await self.conn.fetchrow(
            "SELECT task_id, template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_MONITOR_ACTUAL_RETURNS'",
            opp_id
        )
        self.assertIsNotNone(mon_task)
        mon_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=mon_task["task_id"],
            user_id=self.agent_id,
            outcome="MONITORED",
            viewing_data={"actual_rental_income": 230000.0, "actual_expenses": 22000.0}
        )
        self.assertEqual(mon_res["status"], "COMPLETED")
        mon_act = await self.conn.fetchrow(
            "SELECT description FROM activities WHERE task_id = $1 AND template_id = 'ACT_INVEST_RETURNS_MONITORED'",
            mon_task["task_id"]
        )
        self.assertIn("230,000", mon_act["description"])
        self.assertIn("240,000", mon_act["description"]) # Target from due diligence baseline
        self.assertIn(report_id, mon_act["description"])

        # 4. Next task is TASK_INVEST_PORTFOLIO_REVIEW
        rev_task = await self.conn.fetchrow(
            "SELECT task_id, template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_PORTFOLIO_REVIEW'",
            opp_id
        )
        self.assertIsNotNone(rev_task)
        rev_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=rev_task["task_id"],
            user_id=self.agent_id,
            outcome="HOLD"
        )
        self.assertEqual(rev_res["status"], "COMPLETED")
        rev_act = await self.conn.fetchrow(
            "SELECT description FROM activities WHERE task_id = $1 AND template_id = 'ACT_INVEST_PORTFOLIO_REVIEWED'",
            rev_task["task_id"]
        )
        self.assertIn("HOLD", rev_act["description"])
        self.assertIn("196,000", rev_act["description"]) # Cited due diligence baseline

        # Cleanup
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE', owner_customer_id = NULL WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM investment_due_diligence_reports WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)


if __name__ == "__main__":
    unittest.main()
