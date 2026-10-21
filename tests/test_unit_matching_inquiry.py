import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestUnitMatchingInquiry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_lead62_and_lead77_in_ibrahim_opportunities(self):
        """Verify lead-62 and lead-77 appear in active opportunities for Ibrahim (user-43)."""
        res = self.client.get("/api/v1/opportunities?assigned_user_id=user-43", headers={"X-User-ID": "user-43"})
        self.assertEqual(res.status_code, 200)
        opps = res.json()["data"]
        lead_ids = [o["lead_id"] for o in opps]
        self.assertIn("lead-62", lead_ids, "lead-62 must be present in Ibrahim's opportunities")
        self.assertIn("lead-77", lead_ids, "lead-77 must be present in Ibrahim's opportunities")

        # Verify their stages and values
        opp_62 = next(o for o in opps if o["lead_id"] == "lead-62")
        self.assertIn(opp_62["stage"], ("QUALIFIED", "WON", "CLOSED_WON"))
        self.assertEqual(opp_62["expected_value"], 15000000.0)
        self.assertEqual(opp_62["inquiry_type"], "INVESTMENT")
        self.assertEqual(opp_62["preferred_property_type_name"], "Building")

        opp_77 = next(o for o in opps if o["lead_id"] == "lead-77")
        self.assertIn(opp_77["stage"], ("QUALIFIED", "WON", "CLOSED_WON"))
        self.assertEqual(opp_77["expected_value"], 35000.0)

    def test_opportunity_units_endpoint_fields(self):
        """Verify opportunity units endpoint returns rich properties including owner, asking and rent prices."""
        # Check opp-498 (lead-62)
        res = self.client.get("/api/v1/sales/opportunities/opportunity-498/units")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("data", data)
        self.assertIsInstance(data["data"], list)

    def test_units_endpoint_has_owner_info(self):
        """Verify units endpoint includes owner_name and owner_mobile."""
        res = self.client.get("/api/v1/units?page_size=5")
        self.assertEqual(res.status_code, 200)
        units = res.json()["data"]
        self.assertGreater(len(units), 0)
        unit0 = units[0]
        self.assertIn("unit_id", unit0)
        self.assertIn("unit_number", unit0)
        self.assertIn("owner_name", unit0)
        self.assertIn("owner_mobile", unit0)
        self.assertIn("asking_price", unit0)
        self.assertIn("rent_price", unit0)

    def test_tasks_include_inquiry_type(self):
        """Verify tasks endpoint returns inquiry_type."""
        res = self.client.get("/api/v1/tasks?page_size=10")
        self.assertEqual(res.status_code, 200)
        tasks = res.json()["data"]
        self.assertGreater(len(tasks), 0)
        task0 = tasks[0]
        self.assertIn("inquiry_type", task0)

    def test_lead62_has_no_infinite_loop_pending_tasks(self):
        """Verify lead-62 does not have duplicate pending tasks in an infinite loop."""
        res = self.client.get("/api/v1/tasks?lead_id=lead-62&status=OPEN")
        self.assertEqual(res.status_code, 200)
        tasks = res.json()["data"]
        self.assertEqual(len(tasks), 0, "Lead-62 investment lifecycle is complete; should have no pending loop tasks")

    def test_rental_commission_and_contract_in_finance(self):
        """Verify rental contract and broker commission for lead-77 appear in finance."""
        res = self.client.get("/api/v1/contracts?search=TEN-202610-8328", headers={"X-User-ID": "user-19"})
        self.assertEqual(res.status_code, 200)
        contracts = res.json()["data"]
        self.assertTrue(any(c["contract_number"] == "TEN-202610-8328" and c["contract_type"] == "RENT" for c in contracts))

        res_comm = self.client.get("/api/v1/commissions", headers={"X-User-ID": "user-19"})
        self.assertEqual(res_comm.status_code, 200)
        comms = res_comm.json()["data"]
        comm_77 = next((cm for cm in comms if cm["contract_number"] == "TEN-202610-8328"), None)
        self.assertIsNotNone(comm_77)
        self.assertEqual(comm_77["amount"], 875.0)
        self.assertEqual(comm_77["rate"], 2.5)
        self.assertEqual(comm_77["user_name"], "Ibrahim Alnemari")

    def test_task_9292_assigned_to_accountant(self):
        """Verify task-9292 and TASK_RENT_COLLECTION_MONITORING belong to ACCOUNTANT role."""
        res = self.client.get("/api/v1/tasks/task-9292")
        self.assertEqual(res.status_code, 200)
        task = res.json()["data"]
        self.assertEqual(task["task_id"], "task-9292")
        self.assertEqual(task["assigned_user_id"], "user-19")
        self.assertIn("المالية", task["title"])

if __name__ == "__main__":
    unittest.main()
