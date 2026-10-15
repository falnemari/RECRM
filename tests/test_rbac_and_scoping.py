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

        # An agent with OWN scope must only see a subset of customers
        self.assertLess(user3_total, sysadmin_total)
        self.assertEqual(user3_total, 5)
        self.assertEqual(sysadmin_total, 129)

if __name__ == "__main__":
    unittest.main()

