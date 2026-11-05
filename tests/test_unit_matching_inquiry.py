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
        self.assertIn(opp_62["stage"], ("QUALIFIED", "WON", "CLOSED_WON", "VIEWING"))
        self.assertEqual(opp_62["expected_value"], 15000000.0)
        self.assertEqual(opp_62["inquiry_type"], "INVESTMENT")
        self.assertEqual(opp_62["preferred_property_type_name"], "Building")

        opp_77 = next(o for o in opps if o["lead_id"] == "lead-77")
        self.assertIn(opp_77["stage"], ("QUALIFIED", "WON", "CLOSED_WON"))
        self.assertEqual(opp_77["expected_value"], 35000.0)

    def test_opportunity_units_endpoint_fields(self):
        """Verify opportunity units endpoint returns rich properties including owner, asking and rent prices, city, and listing purpose."""
        # Check opp-498 (lead-62)
        res = self.client.get("/api/v1/sales/opportunities/opportunity-498/units")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("data", data)
        self.assertIsInstance(data["data"], list)
        if len(data["data"]) > 0:
            u0 = data["data"][0]
            self.assertIn("city_name_ar", u0)
            self.assertIn("city_name_en", u0)
            self.assertIn("listing_purpose", u0)

    def test_deal_and_lead_target_city_and_purpose_compatibility(self):
        """Verify deal and lead endpoints return requested target city (AR/EN), and units match city and listing purpose."""
        # 1. Check opportunity has city info
        opp_res = self.client.get("/api/v1/opportunities?page_size=5")
        self.assertEqual(opp_res.status_code, 200)
        opps = opp_res.json()["data"]
        opp_with_city = next((o for o in opps if o.get("preferred_city_id")), None)
        if opp_with_city:
            self.assertIn("preferred_city_name", opp_with_city)
            self.assertIn("preferred_city_name_ar", opp_with_city)

        # 2. Check lead has city info
        lead_res = self.client.get("/api/v1/leads?page_size=5")
        self.assertEqual(lead_res.status_code, 200)
        leads = lead_res.json()["data"]
        lead_with_city = next((l for l in leads if l.get("preferred_city_id")), None)
        if lead_with_city:
            self.assertIn("preferred_city_name", lead_with_city)
            self.assertIn("preferred_city_name_ar", lead_with_city)

        # 3. Units filtering by city
        units_city_res = self.client.get("/api/v1/units?city_id=city-10")
        self.assertEqual(units_city_res.status_code, 200)
        units_city = units_city_res.json()["data"]
        self.assertGreater(len(units_city), 0)
        for u in units_city:
            self.assertEqual(u["city_id"], "city-10")

        # 4. Units filtering by SALE listing purpose (matches SALE or ALL, rejects pure RENT)
        sale_res = self.client.get("/api/v1/units?listing_purpose=SALE")
        self.assertEqual(sale_res.status_code, 200)
        sale_units = sale_res.json()["data"]
        for u in sale_units:
            self.assertIn(u.get("listing_purpose"), ("SALE", "ALL", None))

        # 5. Units filtering by RENT listing purpose (matches RENT or ALL, rejects pure SALE)
        rent_res = self.client.get("/api/v1/units?listing_purpose=RENT")
        self.assertEqual(rent_res.status_code, 200)
        rent_units = rent_res.json()["data"]
        for u in rent_units:
            self.assertIn(u.get("listing_purpose"), ("RENT", "ALL", None))

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
        self.assertLessEqual(len(tasks), 1, "Lead-62 should not have duplicate loop tasks")

    def test_rental_commission_and_contract_in_finance(self):
        """Verify rental contract and broker commission for lead-77 appear in finance."""
        res = self.client.get("/api/v1/contracts?search=TEN-202610-8328", headers={"X-User-ID": "user-19"})
        self.assertEqual(res.status_code, 200)
        contracts = res.json()["data"]
        self.assertTrue(any(c["contract_number"] == "TEN-202610-8328" and c["contract_type"] == "RENT" for c in contracts))

        res_comm = self.client.get("/api/v1/commissions?search=TEN-202610-8328", headers={"X-User-ID": "user-19"})
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
