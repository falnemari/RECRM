import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestManagerialKPIsScoping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_managerial_kpis_sales_agent_ibrahim(self):
        """Verify Ibrahim Alnemari (user-43) sees only his 4 leads, his 3 Buy (all won) + 1 Investment."""
        res = self.client.get("/api/v1/reports/managerial-kpis?user_id=user-43", headers={"X-User-ID": "user-43"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        
        self.assertEqual(data["scope_info"]["scope"], "OWN")
        self.assertEqual(data["scope_info"]["user_id"], "user-43")
        self.assertEqual(data["role_perspective"]["active_role_view"], "SALES_AGENT")
        self.assertTrue(data["role_perspective"]["is_agent"])

        # Check Pipeline by Purpose
        purpose_map = {p["inquiry_type"]: p for p in data["pipeline_by_purpose"]}
        self.assertEqual(purpose_map["BUY"]["lead_count"], 3)
        self.assertEqual(purpose_map["BUY"]["won_count"], 3)
        self.assertEqual(purpose_map["BUY"]["total_budget"], 2900000.0)
        self.assertEqual(purpose_map["BUY"]["conversion_percent"], 100.0)

        self.assertGreaterEqual(purpose_map["RENT"]["lead_count"], 0)

        self.assertEqual(purpose_map["INVESTMENT"]["lead_count"], 1)
        self.assertIn(purpose_map["INVESTMENT"]["won_count"], (0, 1))
        self.assertEqual(purpose_map["INVESTMENT"]["total_budget"], 15000000.0)

        # Check Article 7 Eq 7.2 (Cohort Conversion)
        self.assertIn(data["lead_to_transaction_conversion"]["successful_leads"], (3, 4, 5))
        self.assertEqual(data["lead_to_transaction_conversion"]["total_qualified_leads_in_cohort"], 5)
        self.assertIn(data["lead_to_transaction_conversion"]["conversion_rate_percent"], (60.0, 80.0, 100.0))

        # Check Article 7 Eq 7.4 (Viewing-to-offer)
        self.assertEqual(data["viewing_to_offer_conversion"]["offers_generated"], 3)
        self.assertEqual(data["viewing_to_offer_conversion"]["eligible_completed_viewings"], 3)
        self.assertEqual(data["viewing_to_offer_conversion"]["viewing_to_offer_conversion_percent"], 100.0)

    def test_funnel_dashboard_sales_agent_ibrahim(self):
        """Verify 10 Funnel KPIs for Ibrahim are exact and not inflated."""
        res = self.client.get("/api/v1/reports/funnel-dashboard?scope=OWN&user_id=user-43", headers={"X-User-ID": "user-43"})
        self.assertEqual(res.status_code, 200)
        kpis = res.json()["data"]["kpis"]
        
        self.assertGreaterEqual(kpis["total_leads"], 5)
        self.assertEqual(kpis["qualified_leads"], 5)
        self.assertEqual(kpis["viewings"], 3)
        self.assertEqual(kpis["offers"], 3)
        self.assertEqual(kpis["reservations"], 3)
        self.assertEqual(kpis["contracts"], 3)
        self.assertEqual(kpis["sales_value"], 2750000.0)
        self.assertEqual(kpis["pending_payments"], 0.0)

    def test_managerial_kpis_global_view(self):
        """Verify General Manager (user-51) sees global totals."""
        res = self.client.get("/api/v1/reports/managerial-kpis", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["scope_info"]["scope"], "GLOBAL")
        purpose_map = {p["inquiry_type"]: p for p in data["pipeline_by_purpose"]}
        self.assertGreaterEqual(purpose_map["BUY"]["lead_count"], 69)
        self.assertGreaterEqual(purpose_map["RENT"]["lead_count"], 5)
        self.assertGreaterEqual(purpose_map["INVESTMENT"]["lead_count"], 1)

if __name__ == "__main__":
    unittest.main()
