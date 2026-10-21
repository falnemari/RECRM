import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestPagesDatabaseFetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_tasks_summary_across_roles(self):
        """Ensure /api/v1/tasks/summary never throws 500 for any user role."""
        users = ["user-43", "user-27", "user-5", "user-51", "GUEST", None]
        for u in users:
            headers = {"X-User-ID": u} if u else {}
            res = self.client.get("/api/v1/tasks/summary", headers=headers)
            self.assertEqual(res.status_code, 200, f"Failed for user {u}: {res.text}")
            data = res.json().get("data", {})
            self.assertIn("open_tasks", data)
            self.assertIn("total_activities", data)
            self.assertIn("total_communications", data)
            self.assertIn("total_viewings", data)

    def test_tasks_list_across_roles(self):
        """Ensure /api/v1/tasks fetches database records accurately."""
        for u in ["user-43", "user-27", "user-5", "user-51"]:
            res = self.client.get("/api/v1/tasks", headers={"X-User-ID": u})
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", [])
            self.assertIsInstance(data, list)

    def test_finance_contracts_across_roles(self):
        """Ensure /api/v1/contracts and finance summary work for managers and staff."""
        # Contracts access for sales agents and managers
        for u in ["user-5", "user-51", "user-43"]:
            res = self.client.get("/api/v1/contracts", headers={"X-User-ID": u})
            self.assertEqual(res.status_code, 200, f"Contracts failed for {u}: {res.text}")
            
        # Finance summary access for managers, accountants, and sysadmin
        for u in ["user-5", "user-51", "user-1"]:
            res_sum = self.client.get("/api/v1/finance/summary", headers={"X-User-ID": u})
            self.assertEqual(res_sum.status_code, 200, f"Finance summary failed for {u}: {res_sum.text}")

    def test_core_pages_endpoints_health(self):
        """Ensure all primary page data endpoints return 200."""
        endpoints = [
            "/api/v1/leads",
            "/api/v1/opportunities",
            "/api/v1/customers",
            "/api/v1/units",
            "/api/v1/buildings",
            "/api/v1/projects",
            "/api/v1/cities",
            "/api/v1/property-types",
            "/api/v1/users",
            "/api/v1/activities",
            "/api/v1/communications",
            "/api/v1/reservations",
            "/api/v1/viewings"
        ]
        for ep in endpoints:
            res = self.client.get(ep, headers={"X-User-ID": "user-51"})
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} failed: {res.text}")

    def test_property_management_database_fetch(self):
        """Ensure Property Management endpoints return 200 with live records."""
        for u in ["user-51", "user-1", "user-5", "user-43"]:
            headers = {"X-User-ID": u}
            # Summary
            res = self.client.get("/api/v1/management/summary", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", {})
            self.assertGreater(data.get("active_tenancies", 0), 0)

            # Tenancies
            res_t = self.client.get("/api/v1/tenancies?page_size=50", headers=headers)
            self.assertEqual(res_t.status_code, 200)
            self.assertGreater(len(res_t.json().get("data", [])), 0)

            # Maintenance tickets
            res_m = self.client.get("/api/v1/maintenance-tickets?page_size=50", headers=headers)
            self.assertEqual(res_m.status_code, 200)
            self.assertGreater(len(res_m.json().get("data", [])), 0)

            # Rent collections
            res_rc = self.client.get("/api/v1/rent-collections?page_size=50", headers=headers)
            self.assertEqual(res_rc.status_code, 200)
            self.assertGreater(len(res_rc.json().get("data", [])), 0)

            # Vendors
            res_v = self.client.get("/api/v1/vendors?page_size=50", headers=headers)
            self.assertEqual(res_v.status_code, 200)
            self.assertGreater(len(res_v.json().get("data", [])), 0)

            # Management contracts
            res_mc = self.client.get("/api/v1/management-contracts?page_size=50", headers=headers)
            self.assertEqual(res_mc.status_code, 200)
            self.assertGreater(len(res_mc.json().get("data", [])), 0)

    def test_documents_vault_database_fetch(self):
        """Ensure Documents & Files endpoints return 200 with live records."""
        for u in ["user-51", "user-1", "user-43"]:
            headers = {"X-User-ID": u}
            res_s = self.client.get("/api/v1/documents/summary", headers=headers)
            self.assertEqual(res_s.status_code, 200)
            self.assertGreater(res_s.json().get("data", {}).get("total_documents", 0), 0)

            res_d = self.client.get("/api/v1/documents?page_size=50", headers=headers)
            self.assertEqual(res_d.status_code, 200)
            self.assertGreater(len(res_d.json().get("data", [])), 0)

            res_dt = self.client.get("/api/v1/document-types", headers=headers)
            self.assertEqual(res_dt.status_code, 200)
            self.assertGreater(len(res_dt.json().get("data", [])), 0)

    def test_marketing_campaigns_database_fetch(self):
        """Ensure Marketing & Campaigns endpoints return 200 with live records."""
        for u in ["user-51", "user-1", "user-5", "user-43"]:
            headers = {"X-User-ID": u}
            res_s = self.client.get("/api/v1/marketing/summary", headers=headers)
            self.assertEqual(res_s.status_code, 200)
            self.assertGreater(res_s.json().get("data", {}).get("total_campaigns", 0), 0)

            res_c = self.client.get("/api/v1/campaigns?page=1&page_size=50", headers=headers)
            self.assertEqual(res_c.status_code, 200)
            self.assertGreater(len(res_c.json().get("data", [])), 0)

            res_ev = self.client.get("/api/v1/lead-events?page=1&page_size=40", headers=headers)
            self.assertEqual(res_ev.status_code, 200)
            self.assertGreater(len(res_ev.json().get("data", [])), 0)

    def test_property_listings_database_fetch(self):
        """Ensure Property Listings endpoints return 200 with live records."""
        for u in ["user-51", "user-1", "user-5", "user-43"]:
            headers = {"X-User-ID": u}
            res_s = self.client.get("/api/v1/listings/summary", headers=headers)
            self.assertEqual(res_s.status_code, 200)
            self.assertGreater(res_s.json().get("data", {}).get("total_listings", 0), 0)

            res_l = self.client.get("/api/v1/listings?page=1&page_size=50", headers=headers)
            self.assertEqual(res_l.status_code, 200)
            self.assertGreater(len(res_l.json().get("data", [])), 0)

if __name__ == "__main__":
    unittest.main()

