import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestRBACAndScoping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Using context manager so FastAPI lifespan initializes the asyncpg DB pool
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_sysadmin_can_access_admin_summary(self):
        res = self.client.get("/api/v1/admin/summary", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("total_users", data)
        self.assertIn("total_branches", data)

    def test_sales_agent_blocked_from_admin_summary(self):
        res = self.client.get("/api/v1/admin/summary", headers={"X-User-ID": "user-3"})
        self.assertEqual(res.status_code, 403)

    def test_sysadmin_can_access_finance_summary(self):
        res = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("total_contracts", data)

    def test_accountant_can_access_finance_summary(self):
        res = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-30"})
        self.assertEqual(res.status_code, 200)

    def test_sales_agent_blocked_from_finance_summary(self):
        res = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-3"})
        self.assertEqual(res.status_code, 403)

    def test_user27_sales_agent_with_customer_read_can_see_all_customers(self):
        # user-27 (Shahad Alnemari) is a SALES_AGENT with CUSTOMER_READ and CUSTOMER_WRITE permissions
        res_user27 = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-27"})
        self.assertEqual(res_user27.status_code, 200)
        user27_total = res_user27.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_sysadmin.status_code, 200)
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        # Any user granted CUSTOMER_READ must be qualified to view all customers in the directory
        self.assertEqual(user27_total, sysadmin_total)
        self.assertGreater(user27_total, 0)

    def test_user43_can_see_all_customers(self):
        # user-43 has CUSTOMER_READ and CUSTOMER_WRITE permissions
        res_user43 = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-43"})
        self.assertEqual(res_user43.status_code, 200)
        user43_total = res_user43.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_sysadmin.status_code, 200)
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        self.assertEqual(user43_total, sysadmin_total)
        self.assertGreater(user43_total, 0)

    def test_user_without_customer_read_is_scoped(self):
        # user-21 (Document Control) does NOT have CUSTOMER_READ or CUSTOMER_WRITE permissions
        res_user21 = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-21"})
        self.assertEqual(res_user21.status_code, 200)
        user21_total = res_user21.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        # Users lacking CUSTOMER_READ are restricted to only customers tied to their operational records
        self.assertLess(user21_total, sysadmin_total)

    def test_customer_lookup_for_lead_creation_bypasses_scope(self):
        # Even for a user without general CUSTOMER_READ, customer search/lookup for transactions returns all matching records
        res_lookup = self.client.get("/api/v1/customers?for_lookup=true", headers={"X-User-ID": "user-21"})
        self.assertEqual(res_lookup.status_code, 200)
        lookup_total = res_lookup.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        self.assertEqual(lookup_total, sysadmin_total)

    def test_create_lead_through_user27(self):
        # Verify lead creation through user-27 works seamlessly for existing customer
        payload = {
            "customer_id": "customer-21",
            "assigned_user_id": "user-27",
            "inquiry_type": "BUY",
            "priority": "HIGH"
        }
        res = self.client.post("/api/v1/leads", json=payload, headers={"X-User-ID": "user-27"})
        self.assertEqual(res.status_code, 201)
        lead_data = res.json()["data"]
        self.assertEqual(lead_data["assigned_user_id"], "user-27")
        self.assertEqual(lead_data["customer_id"], "customer-21")

    def test_accountant_user19_can_query_tasks_and_see_task_3796(self):
        # user-19 (Demo Agent 26, Accountant) has earnest deposit followup task-3796
        res = self.client.get("/api/v1/tasks?assigned_user_id=user-19", headers={"X-User-ID": "user-19"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["meta"]["total"], 1)
        task_ids = [t["task_id"] for t in data["data"]]
        self.assertIn("task-3796", task_ids)

        # Also verify accountant can query active OPEN/PENDING tasks
        res_open = self.client.get("/api/v1/tasks?assigned_user_id=user-19&status=OPEN", headers={"X-User-ID": "user-19"})
        self.assertEqual(res_open.status_code, 200)
        self.assertGreaterEqual(res_open.json()["meta"]["total"], 1)

    def test_tasks_status_open_includes_pending_tasks(self):
        # Querying status=OPEN must include active PENDING operational tasks
        res = self.client.get("/api/v1/tasks?status=OPEN", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data["meta"]["total"], 0)

        # Summary open_tasks must also count pending tasks
        sum_res = self.client.get("/api/v1/tasks/summary", headers={"X-User-ID": "user-51"})
        self.assertEqual(sum_res.status_code, 200)
        self.assertGreater(sum_res.json()["data"]["open_tasks"], 0)

    def test_reservation_agreed_price_reflects_accepted_offer(self):
        # RES-000004 / res-180 has unit asking_price 1,100,000 SAR but accepted offer 1,000,000 SAR
        res = self.client.get("/api/v1/reservations/res-180", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["reservation_id"], "res-180")
        self.assertEqual(data["asking_price"], 1100000.0)
        self.assertEqual(data["agreed_price"], 1000000.0)
        self.assertEqual(data["accepted_offer_amount"], 1000000.0)
        self.assertEqual(data["deposit_amount"], 50000.0)

    def test_contract_legal_review_sop_guide_and_task_id_resolution(self):
        # 1. Fetch by template_id
        res = self.client.get("/api/v1/sop-guide/TASK_CONTRACT_INTERNAL_REVIEW")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["procedure_code"], "TASK_CONTRACT_INTERNAL_REVIEW")
        self.assertEqual(data["responsible_role_code"], "LEGAL")
        self.assertGreaterEqual(len(data["execution_steps_ar"]), 4)
        self.assertGreaterEqual(len(data["execution_steps_en"]), 4)

        # 2. Fetch by live task_id (task-5481)
        res_task = self.client.get("/api/v1/sop-guide/task-5481")
        self.assertEqual(res_task.status_code, 200)
        self.assertEqual(res_task.json()["data"]["procedure_code"], "TASK_CONTRACT_INTERNAL_REVIEW")

        # 3. Verify other contract stage tasks also resolve
        for code in ["TASK_CONTRACT_SIGNATURE", "TASK_CONTRACT_RECONCILIATION", "TASK_CONTRACT_HANDOVER"]:
            c_res = self.client.get(f"/api/v1/sop-guide/{code}")
            self.assertEqual(c_res.status_code, 200)

if __name__ == "__main__":
    unittest.main()

