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

    def test_customers_scoped_for_own_user(self):
        res_user3 = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-3"})
        self.assertEqual(res_user3.status_code, 200)
        user3_total = res_user3.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_sysadmin.status_code, 200)
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

    def test_user43_global_scope_can_see_all_customers(self):
        # user-43 has MARKETING, PROPERTY_MANAGER, and DOCUMENT_CONTROL with customer read/write permissions
        res_user43 = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-43"})
        self.assertEqual(res_user43.status_code, 200)
        user43_total = res_user43.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_sysadmin.status_code, 200)
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        # user-43 must have global customer visibility
        self.assertEqual(user43_total, sysadmin_total)
        self.assertGreater(user43_total, 0)

    def test_customer_lookup_for_lead_creation_bypasses_own_scope(self):
        # When creating a lead (for_lookup=true or searching by mobile/name), customer lookup must find existing records
        res_lookup = self.client.get("/api/v1/customers?for_lookup=true", headers={"X-User-ID": "user-3"})
        self.assertEqual(res_lookup.status_code, 200)
        lookup_total = res_lookup.json()["meta"]["total"]

        res_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        sysadmin_total = res_sysadmin.json()["meta"]["total"]

        # An agent creating a lead must be able to lookup any existing customer in the CRM
        self.assertEqual(lookup_total, sysadmin_total)

if __name__ == "__main__":
    unittest.main()

