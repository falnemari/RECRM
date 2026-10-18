import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.routers.auth import resolve_user_data_scope

class TestUsersPermissionsAndScoping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_all_users_revised_and_scoped(self):
        res = self.client.get("/api/v1/auth/users", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        users = res.json()["data"]
        self.assertEqual(len(users), 51)

        # Verify active sales agents have OWN scope
        for uid in ["user-27", "user-43", "user-3", "user-13", "user-16"]:
            u = next((item for item in users if item["user_id"] == uid), None)
            self.assertIsNotNone(u, f"User {uid} not found")
            self.assertIn("SALES_AGENT", u["roles"])
            self.assertEqual(u["effective_scope"], "OWN")

        # Verify branch managers have BRANCH scope
        for uid in ["user-1", "user-2", "user-5", "user-9", "user-50"]:
            u = next((item for item in users if item["user_id"] == uid), None)
            self.assertIsNotNone(u, f"Branch manager {uid} not found")
            self.assertIn("SALES_MANAGER", u["roles"])
            self.assertEqual(u["effective_scope"], "BRANCH")

        # Verify sysadmin has GLOBAL scope
        u51 = next((item for item in users if item["user_id"] == "user-51"), None)
        self.assertIsNotNone(u51)
        self.assertIn("SYS_ADMIN", u51["roles"])
        self.assertEqual(u51["effective_scope"], "GLOBAL")

    def test_agents_can_see_all_customers_for_lead_creation(self):
        # Both user-27 and user-43 must see all customers in organization directory
        r_sysadmin = self.client.get("/api/v1/customers", headers={"X-User-ID": "user-51"})
        total_customers = r_sysadmin.json()["meta"]["total"]
        self.assertGreater(total_customers, 0)

        for agent_id in ["user-27", "user-43"]:
            r_agent = self.client.get("/api/v1/customers", headers={"X-User-ID": agent_id})
            self.assertEqual(r_agent.status_code, 200)
            self.assertEqual(r_agent.json()["meta"]["total"], total_customers)

    def test_agents_can_see_branch_units_inventory(self):
        r_sysadmin = self.client.get("/api/v1/units", headers={"X-User-ID": "user-51"})
        total_units = r_sysadmin.json()["meta"]["total"]
        self.assertGreater(total_units, 0)

        for agent_id in ["user-27", "user-43"]:
            r_agent = self.client.get("/api/v1/units", headers={"X-User-ID": agent_id})
            self.assertEqual(r_agent.status_code, 200)
            self.assertEqual(r_agent.json()["meta"]["total"], total_units)

    def test_agents_isolated_to_own_leads(self):
        r_u27 = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-27"})
        self.assertEqual(r_u27.status_code, 200)
        leads_u27 = r_u27.json()["data"]

        r_u43 = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-43"})
        self.assertEqual(r_u43.status_code, 200)
        leads_u43 = r_u43.json()["data"]

        # Verify all returned leads belong to requesting agent
        for lead in leads_u27:
            self.assertEqual(lead["assigned_user_id"], "user-27")
        for lead in leads_u43:
            self.assertEqual(lead["assigned_user_id"], "user-43")

    def test_agents_blocked_from_cross_agent_leads(self):
        r_u27 = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-27"})
        u27_lead_id = r_u27.json()["data"][0]["lead_id"]

        # user-43 tries to get user-27's lead -> 403 Forbidden
        r_cross = self.client.get(f"/api/v1/leads/{u27_lead_id}", headers={"X-User-ID": "user-43"})
        self.assertEqual(r_cross.status_code, 403)

        # user-27 gets own lead -> 200 OK
        r_own = self.client.get(f"/api/v1/leads/{u27_lead_id}", headers={"X-User-ID": "user-27"})
        self.assertEqual(r_own.status_code, 200)

        # sysadmin gets lead -> 200 OK
        r_admin = self.client.get(f"/api/v1/leads/{u27_lead_id}", headers={"X-User-ID": "user-51"})
        self.assertEqual(r_admin.status_code, 200)

    def test_agents_blocked_from_cross_agent_opportunities(self):
        r_u27 = self.client.get("/api/v1/opportunities", headers={"X-User-ID": "user-27"})
        u27_opp_id = r_u27.json()["data"][0]["opportunity_id"]

        # user-43 tries to get user-27's opportunity -> 403 Forbidden
        r_cross = self.client.get(f"/api/v1/opportunities/{u27_opp_id}", headers={"X-User-ID": "user-43"})
        self.assertEqual(r_cross.status_code, 403)

        # user-27 gets own opportunity -> 200 OK
        r_own = self.client.get(f"/api/v1/opportunities/{u27_opp_id}", headers={"X-User-ID": "user-27"})
        self.assertEqual(r_own.status_code, 200)

    def test_agents_blocked_from_cross_agent_tasks(self):
        r_u27 = self.client.get("/api/v1/tasks", headers={"X-User-ID": "user-27"})
        u27_task_id = r_u27.json()["data"][0]["task_id"]

        # user-43 tries to get user-27's task -> 403 Forbidden
        r_cross = self.client.get(f"/api/v1/tasks/{u27_task_id}", headers={"X-User-ID": "user-43"})
        self.assertEqual(r_cross.status_code, 403)

        # user-27 gets own task -> 200 OK
        r_own = self.client.get(f"/api/v1/tasks/{u27_task_id}", headers={"X-User-ID": "user-27"})
        self.assertEqual(r_own.status_code, 200)

    def test_agents_blocked_from_unauthorized_pages_and_summaries(self):
        # Admin Summary is forbidden for agents
        res_admin = self.client.get("/api/v1/admin/summary", headers={"X-User-ID": "user-27"})
        self.assertEqual(res_admin.status_code, 403)

        # Finance Summary is forbidden for agents
        res_fin = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-27"})
        self.assertEqual(res_fin.status_code, 403)

        # Accountant can access finance summary
        res_acc = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-19"})
        self.assertEqual(res_acc.status_code, 200)

        # Sysadmin can access both
        self.assertEqual(self.client.get("/api/v1/admin/summary", headers={"X-User-ID": "user-51"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/finance/summary", headers={"X-User-ID": "user-51"}).status_code, 200)

if __name__ == "__main__":
    unittest.main()
