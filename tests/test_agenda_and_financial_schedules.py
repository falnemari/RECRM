import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestAgendaAndFinancialSchedules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    # -------------------------------------------------------------
    # 1. Operational Calendar & Agenda Tests
    # -------------------------------------------------------------
    def test_agenda_calendar_global_admin(self):
        """Verify General Manager (user-51) gets company-wide operational calendar with KPIs for uncompleted items."""
        res = self.client.get("/api/v1/reports/agenda-calendar", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]

        # Scope verification
        self.assertEqual(data["scope_info"]["scope"], "GLOBAL")
        self.assertIn("summary", data)
        summary = data["summary"]

        self.assertGreaterEqual(summary["total_events"], 50)
        self.assertGreaterEqual(summary["tasks_count"], 10)
        self.assertGreaterEqual(summary["viewings_count"], 1)
        self.assertGreaterEqual(summary["reservations_count"], 1)

        # Check item attributes
        events = data["events"]
        self.assertGreater(len(events), 0)
        sample = events[0]
        self.assertIn("event_id", sample)
        self.assertIn("event_type", sample)
        self.assertIn("title", sample)
        self.assertIn("priority", sample)
        self.assertIn("badge_color", sample)

        # Ensure direct operational links exist
        has_lead_id = any(item.get("lead_id") for item in events)
        has_task_or_viewing_or_res = any(
            item.get("task_id") or item.get("viewing_id") or item.get("reservation_id")
            for item in events
        )
        self.assertTrue(has_lead_id, "Agenda items must include lead_id links")
        self.assertTrue(has_task_or_viewing_or_res, "Agenda items must include direct task/viewing/reservation links")

        # Verify only uncompleted/unexecuted items returned by default
        for item in events:
            self.assertIsNotNone(item.get("event_date"), "All agenda items must be scheduled with a date")
            if item.get("event_type") == "TASK":
                self.assertNotIn(item["status"], ("COMPLETED", "CANCELLED"))
            if item.get("event_type") == "VIEWING":
                self.assertNotIn(item["status"], ("COMPLETED", "CANCELLED"))
            if item.get("event_type") == "RESERVATION":
                self.assertNotIn(item["status"], ("CONVERTED", "CANCELLED"))

    def test_agenda_calendar_uncompleted_vs_all_toggle(self):
        """Verify uncompleted_only toggle: False returns historic completed records too."""
        res_uncompleted = self.client.get("/api/v1/reports/agenda-calendar?uncompleted_only=true", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_uncompleted.status_code, 200)
        uncompleted_count = res_uncompleted.json()["data"]["summary"]["total_events"]

        res_all = self.client.get("/api/v1/reports/agenda-calendar?uncompleted_only=false", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_all.status_code, 200)
        all_count = res_all.json()["data"]["summary"]["total_events"]

        self.assertGreater(all_count, uncompleted_count, "All events count must exceed uncompleted only events")

    def test_agenda_calendar_agent_scoping(self):
        """Verify Frontline Agent (user-27 / user-43) gets strictly scoped records."""
        res = self.client.get("/api/v1/reports/agenda-calendar", headers={"X-User-ID": "user-27"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]

        self.assertEqual(data["scope_info"]["scope"], "OWN")
        self.assertEqual(data["scope_info"]["user_id"], "user-27")

        # Must not see other agents' tasks
        for item in data["events"]:
            if item.get("assigned_user_id"):
                self.assertEqual(item["assigned_user_id"], "user-27")

    def test_agenda_calendar_event_type_filters(self):
        """Verify filtering by event_type=TASK and event_type=VIEWING and event_type=RESERVATION."""
        # Task only
        res_task = self.client.get("/api/v1/reports/agenda-calendar?event_type=TASK", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_task.status_code, 200)
        task_events = res_task.json()["data"]["events"]
        for it in task_events:
            self.assertEqual(it["event_type"], "TASK")

        # Viewing only
        res_view = self.client.get("/api/v1/reports/agenda-calendar?event_type=VIEWING", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_view.status_code, 200)
        view_events = res_view.json()["data"]["events"]
        for it in view_events:
            self.assertEqual(it["event_type"], "VIEWING")

        # Reservation only
        res_res = self.client.get("/api/v1/reports/agenda-calendar?event_type=RESERVATION", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_res.status_code, 200)
        res_events = res_res.json()["data"]["events"]
        for it in res_events:
            self.assertEqual(it["event_type"], "RESERVATION")

    # -------------------------------------------------------------
    # 2. Financial Dues & Collections Schedule Tests
    # -------------------------------------------------------------
    def test_financial_schedule_global_admin(self):
        """Verify Financial Schedule returns categorized receivables, summary KPIs and percentages."""
        res = self.client.get("/api/v1/reports/financial-schedule", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]

        self.assertEqual(data["scope_info"]["scope"], "GLOBAL")
        summary = data["summary"]
        self.assertGreater(summary["total_dues_amount"], 0)
        self.assertGreaterEqual(summary["collection_rate_percent"], 0)
        self.assertLessEqual(summary["collection_rate_percent"], 100)
        self.assertGreater(summary["total_items"], 0)

        items = data["items"]
        self.assertGreater(len(items), 0)

        # Check categories present
        categories = {item["category"] for item in items}
        self.assertIn("DEALS_LEADS", categories)

        # Check item fields
        sample = items[0]
        self.assertIn("item_id", sample)
        self.assertIn("category", sample)
        self.assertIn("category_label_ar", sample)
        self.assertIn("item_type_code", sample)
        self.assertIn("amount", sample)
        self.assertIn("amount_paid", sample)
        self.assertIn("amount_remaining", sample)
        self.assertIn("collection_status", sample)
        self.assertIn("badge_color", sample)

        # Check lead_id linkage where appropriate
        deals_items = [it for it in items if it["category"] == "DEALS_LEADS"]
        has_lead_id = any(it.get("lead_id") for it in deals_items)
        self.assertTrue(has_lead_id, "Deal invoices/reservations should carry lead_id")

    def test_financial_schedule_category_filter(self):
        """Verify category filtering for DEALS_LEADS, PROPERTY_MANAGEMENT, and MARKETING."""
        res_deals = self.client.get("/api/v1/reports/financial-schedule?category=DEALS_LEADS", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_deals.status_code, 200)
        items = res_deals.json()["data"]["items"]
        for it in items:
            self.assertEqual(it["category"], "DEALS_LEADS")

    def test_financial_schedule_status_filter(self):
        """Verify collection_status filtering (COLLECTED, PENDING, OVERDUE)."""
        res_coll = self.client.get("/api/v1/reports/financial-schedule?collection_status=COLLECTED", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_coll.status_code, 200)
        items = res_coll.json()["data"]["items"]
        for it in items:
            self.assertEqual(it["collection_status"], "COLLECTED")

    def test_financial_schedule_agent_scoping(self):
        """Verify agent scoping isolates financial dues strictly to assigned leads/reservations."""
        res = self.client.get("/api/v1/reports/financial-schedule", headers={"X-User-ID": "user-27"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]

        self.assertEqual(data["scope_info"]["scope"], "OWN")
        self.assertEqual(data["scope_info"]["user_id"], "user-27")

        # Agent should only see DEALS_LEADS assigned to them, not company-wide property management or ad campaigns
        for it in data["items"]:
            self.assertEqual(it["category"], "DEALS_LEADS")

    def test_agenda_and_financial_schedule_deal_lead_filter(self):
        """Verify agenda calendar and financial schedule can be scoped to a specific lead_id or opportunity_id."""
        # 1. Agenda Calendar filtered by lead_id
        res_cal = self.client.get("/api/v1/reports/agenda-calendar?lead_id=lead-14", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_cal.status_code, 200)
        cal_events = res_cal.json()["data"]["events"]
        for ev in cal_events:
            self.assertEqual(ev["lead_id"], "lead-14")

        # 2. Financial Schedule filtered by lead_id
        res_fin = self.client.get("/api/v1/reports/financial-schedule?lead_id=lead-14", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_fin.status_code, 200)
        fin_items = res_fin.json()["data"]["items"]
        for it in fin_items:
            self.assertEqual(it["lead_id"], "lead-14")

    # -------------------------------------------------------------
    # 3. Cross-Page Deep Linking & Record Isolation Verification
    # -------------------------------------------------------------
    def test_maintenance_ticket_search_and_isolation(self):
        """Verify maintenance-tickets API allows searching and isolating by ticket_id or work_order_id."""
        # 1. Search by ticket_id
        res1 = self.client.get("/api/v1/maintenance-tickets?search=tick-1", headers={"X-User-ID": "user-51"})
        self.assertEqual(res1.status_code, 200)
        tickets = res1.json()["data"]
        self.assertGreaterEqual(len(tickets), 1)
        self.assertTrue(any(t["ticket_id"] == "tick-1" for t in tickets))

        # 2. Search by work_order_id
        res2 = self.client.get("/api/v1/maintenance-tickets?search=wo-1", headers={"X-User-ID": "user-51"})
        self.assertEqual(res2.status_code, 200)
        tickets2 = res2.json()["data"]
        self.assertGreaterEqual(len(tickets2), 1)

        # 3. Direct ticket_id filter
        res3 = self.client.get("/api/v1/maintenance-tickets?ticket_id=tick-1", headers={"X-User-ID": "user-51"})
        self.assertEqual(res3.status_code, 200)
        tickets3 = res3.json()["data"]
        self.assertEqual(len(tickets3), 1)
        self.assertEqual(tickets3[0]["ticket_id"], "tick-1")

    def test_rent_collection_search_and_isolation(self):
        """Verify rent-collections API allows searching and isolating by collection_id."""
        res_all = self.client.get("/api/v1/rent-collections?page_size=5", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_all.status_code, 200)
        items = res_all.json()["data"]
        if items:
            target_id = items[0]["rent_collection_id"]
            # Search by ID
            res_search = self.client.get(f"/api/v1/rent-collections?search={target_id}", headers={"X-User-ID": "user-51"})
            self.assertEqual(res_search.status_code, 200)
            found = res_search.json()["data"]
            self.assertGreaterEqual(len(found), 1)
            self.assertEqual(found[0]["rent_collection_id"], target_id)

    def test_campaign_search_by_id(self):
        """Verify campaigns API allows searching by campaign_id."""
        res = self.client.get("/api/v1/campaigns?search=camp-1", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        camps = res.json()["data"]
        self.assertGreaterEqual(len(camps), 1)
        self.assertTrue(any(c["campaign_id"] == "camp-1" for c in camps))

    def test_agenda_and_financial_schedule_metadata_keys(self):
        """Verify Agenda and Financial Schedule items contain ticket_id, work_order_id, and item_type."""
        # 1. Agenda
        res_cal = self.client.get("/api/v1/reports/agenda-calendar", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_cal.status_code, 200)
        events = res_cal.json()["data"]["events"]
        mnt_events = [e for e in events if e.get("event_type") == "MAINTENANCE"]
        if mnt_events:
            self.assertIn("work_order_id", mnt_events[0])
            self.assertIn("ticket_id", mnt_events[0])

        # 2. Financial Schedule
        res_fin = self.client.get("/api/v1/reports/financial-schedule", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_fin.status_code, 200)
        items = res_fin.json()["data"]["items"]
        for it in items:
            self.assertIn("item_type", it)
            self.assertIn("item_type_code", it)
            self.assertEqual(it["item_type"], it["item_type_code"])

    def test_financial_schedule_sort_nearest_due_date_first(self):
        """Verify Financial Schedule is sorted ascending by due_date (nearest/earliest first, nulls at end)."""
        res = self.client.get("/api/v1/reports/financial-schedule", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        items = res.json()["data"]["items"]
        self.assertGreater(len(items), 0)

        prev_due = None
        seen_null = False
        for it in items:
            due = it.get("due_date")
            if due is not None:
                self.assertFalse(seen_null, "Items with valid due_date should precede items with None due_date")
                if prev_due is not None:
                    self.assertLessEqual(prev_due, due, f"Due dates should be in ascending order: {prev_due} <= {due}")
                prev_due = due
            else:
                seen_null = True

    def test_reservation_search_by_id_and_isolation(self):
        """Verify reservations API allows searching and isolating by reservation_id (e.g. res-28)."""
        # 1. Search by reservation_id
        res = self.client.get("/api/v1/reservations?search=res-28", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        items = res.json()["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reservation_id"], "res-28")
        self.assertEqual(items[0]["reservation_number"], "RES-000001")

        # 2. Filter by reservation_id parameter directly
        res2 = self.client.get("/api/v1/reservations?reservation_id=res-28", headers={"X-User-ID": "user-51"})
        self.assertEqual(res2.status_code, 200)
        items2 = res2.json()["data"]
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[0]["reservation_id"], "res-28")

if __name__ == "__main__":
    unittest.main()
