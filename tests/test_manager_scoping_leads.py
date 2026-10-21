import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestManagerScopingLeads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_general_manager_loads_all_leads_directly(self):
        # 1. Via X-User-ID header
        res_hdr = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_hdr.status_code, 200)
        total_hdr = res_hdr.json()["meta"]["total"]
        self.assertGreaterEqual(total_hdr, 70)

        # 2. Via assigned_user_id query param (selecting General Manager in filter)
        res_param = self.client.get("/api/v1/leads?assigned_user_id=user-51")
        self.assertEqual(res_param.status_code, 200)
        total_param = res_param.json()["meta"]["total"]
        self.assertEqual(total_param, total_hdr)

    def test_branch_manager_loads_branch_leads_directly(self):
        # Nawaaf Alzahrani (user-5) is Makkah Branch Manager (branch-4)
        # 1. Via X-User-ID header
        res_hdr = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-5"})
        self.assertEqual(res_hdr.status_code, 200)
        total_hdr = res_hdr.json()["meta"]["total"]
        self.assertGreaterEqual(total_hdr, 65)

        # 2. Via assigned_user_id query param (selecting Branch Manager in filter)
        res_param = self.client.get("/api/v1/leads?assigned_user_id=user-5")
        self.assertEqual(res_param.status_code, 200)
        total_param = res_param.json()["meta"]["total"]
        self.assertEqual(total_param, total_hdr)

    def test_sales_agent_ibrahim_loads_own_leads_directly(self):
        # Ibrahim Alnemari (user-43) is Sales Agent
        # 1. Via X-User-ID header
        res_hdr = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-43"})
        self.assertEqual(res_hdr.status_code, 200)
        total_hdr = res_hdr.json()["meta"]["total"]
        self.assertGreaterEqual(total_hdr, 4)

        # 2. Via assigned_user_id query param
        res_param = self.client.get("/api/v1/leads?assigned_user_id=user-43")
        self.assertEqual(res_param.status_code, 200)
        total_param = res_param.json()["meta"]["total"]
        self.assertEqual(total_param, total_hdr)

    def test_sales_agent_attempt_cross_scope_is_enforced(self):
        # Ibrahim Alnemari (user-43) attempting to query GM user-51 is kept to OWN scope
        res_self = self.client.get("/api/v1/leads", headers={"X-User-ID": "user-43"})
        own_total = res_self.json()["meta"]["total"]
        res = self.client.get("/api/v1/leads?assigned_user_id=user-51", headers={"X-User-ID": "user-43"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["meta"]["total"], own_total)

    def test_opportunities_scoping_gm_bm_agent(self):
        # GM Fahad
        res_gm = self.client.get("/api/v1/opportunities?assigned_user_id=user-51")
        self.assertEqual(res_gm.status_code, 200)
        gm_total = res_gm.json()["meta"]["total"]
        self.assertGreaterEqual(gm_total, 6)

        # BM Nawaaf (Makkah)
        res_bm = self.client.get("/api/v1/opportunities?assigned_user_id=user-5")
        self.assertEqual(res_bm.status_code, 200)
        bm_total = res_bm.json()["meta"]["total"]
        self.assertGreaterEqual(bm_total, 4)

        # Sales Agent Ibrahim (user-43)
        res_ag = self.client.get("/api/v1/opportunities?assigned_user_id=user-43")
        self.assertEqual(res_ag.status_code, 200)
        ag_total = res_ag.json()["meta"]["total"]
        self.assertEqual(ag_total, 5)

    def test_tasks_scoping_gm_bm_agent(self):
        # GM Fahad
        res_gm = self.client.get("/api/v1/tasks?assigned_user_id=user-51")
        self.assertEqual(res_gm.status_code, 200)
        self.assertGreaterEqual(res_gm.json()["meta"]["total"], 100)

        # BM Nawaaf (Makkah)
        res_bm = self.client.get("/api/v1/tasks?assigned_user_id=user-5")
        self.assertEqual(res_bm.status_code, 200)
        self.assertGreaterEqual(res_bm.json()["meta"]["total"], 50)

        # Sales Agent Ibrahim (user-43)
        res_ag = self.client.get("/api/v1/tasks?assigned_user_id=user-43")
        self.assertEqual(res_ag.status_code, 200)
        self.assertGreaterEqual(res_ag.json()["meta"]["total"], 20)

if __name__ == "__main__":
    unittest.main()

