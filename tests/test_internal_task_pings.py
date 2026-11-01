import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestInternalTaskPings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_01_create_internal_ping(self):
        """Verify sending an internal task reminder ping with context snapshot."""
        payload = {
            "recipient_role": "DIRECT_MANAGER",
            "context_type": "TASK",
            "context_id": "TSK-102",
            "context_snapshot": {
                "rowId": "TSK-102",
                "title": "متابعة العميل وإجراء الاتصال الأولي",
                "customer": "سلطان بن عبدالعزيز",
                "amount": "1,250,000 SAR",
                "assignedUser": "سلطان الغامدي"
            },
            "message_text": "تذكير: نرجو استكمال الاتصال بالعميل قبل انتهاء مهلة الـ 30 دقيقة المعتمدة.",
            "urgency_level": "URGENT",
            "is_archived": False
        }
        res = self.client.post("/api/v1/internal-pings", json=payload, headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertTrue(data["ping_id"].startswith("PNG-"))
        self.assertEqual(data["sender_user_id"], "user-51")
        self.assertEqual(data["context_type"], "TASK")
        self.assertEqual(data["context_id"], "TSK-102")
        self.assertEqual(data["urgency_level"], "URGENT")
        self.assertFalse(data["is_read"])
        self.assertFalse(data["is_archived"])
        self.assertIn("سلطان الغامدي", data["context_snapshot"].get("assignedUser", ""))

    def test_02_get_inbox_and_unread_counts(self):
        """Verify retrieving pings inbox with summary and filter tabs."""
        res = self.client.get("/api/v1/internal-pings/inbox?filter_type=ALL", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("pings", data)
        self.assertIn("summary", data)
        summary = data["summary"]
        self.assertGreaterEqual(summary["total_count"], 1)

    def test_03_toggle_read_status(self):
        """Verify toggling ping read/unread status."""
        # Create ping first
        payload = {
            "recipient_role": "ACCOUNTANT",
            "recipient_user_id": "user-51",
            "context_type": "RENT_COLLECTION",
            "context_id": "CL-504",
            "context_snapshot": {
                "rowId": "CL-504",
                "title": "قسط إيجار ربع سنوي",
                "amount": "45,000 SAR"
            },
            "message_text": "يرجى التحقق من تحويل الدفعة وإصدار السند.",
            "urgency_level": "NORMAL",
            "is_archived": False
        }
        create_res = self.client.post("/api/v1/internal-pings", json=payload, headers={"X-User-ID": "user-5"})
        self.assertEqual(create_res.status_code, 201)
        ping_id = create_res.json()["data"]["ping_id"]

        # Mark as read
        read_res = self.client.patch(f"/api/v1/internal-pings/{ping_id}/read", headers={"X-User-ID": "user-51"})
        self.assertEqual(read_res.status_code, 200)
        self.assertTrue(read_res.json()["data"]["is_read"])
        self.assertIsNotNone(read_res.json()["data"]["read_at"])

        # Mark as unread
        unread_res = self.client.patch(f"/api/v1/internal-pings/{ping_id}/read", headers={"X-User-ID": "user-51"})
        self.assertEqual(unread_res.status_code, 200)
        self.assertFalse(unread_res.json()["data"]["is_read"])

    def test_04_toggle_archive_as_proof(self):
        """Verify archiving a ping as proof and retrieving via ARCHIVED filter."""
        payload = {
            "recipient_role": "DIRECT_MANAGER",
            "recipient_user_id": "user-51",
            "context_type": "TASK",
            "context_id": "TSK-999",
            "context_snapshot": {"title": "إثبات سداد العربون"},
            "message_text": "إثبات رسمي: تم تنبيه الإدارة باستلام شيك العربون في الموعد المحدد.",
            "urgency_level": "URGENT",
            "is_archived": False
        }
        create_res = self.client.post("/api/v1/internal-pings", json=payload, headers={"X-User-ID": "user-5"})
        ping_id = create_res.json()["data"]["ping_id"]

        # Archive as proof
        arch_res = self.client.patch(f"/api/v1/internal-pings/{ping_id}/archive", headers={"X-User-ID": "user-51"})
        self.assertEqual(arch_res.status_code, 200)
        self.assertTrue(arch_res.json()["data"]["is_archived"])
        self.assertIsNotNone(arch_res.json()["data"]["archived_at"])

        # Check in archived inbox filter
        inbox_res = self.client.get("/api/v1/internal-pings/inbox?filter_type=ARCHIVED", headers={"X-User-ID": "user-51"})
        self.assertEqual(inbox_res.status_code, 200)
        archived_ids = [p["ping_id"] for p in inbox_res.json()["data"]["pings"]]
        self.assertIn(ping_id, archived_ids)

    def test_05_cleanup_expired_retention_policy(self):
        """Verify executing data retention cleanup for transient pings while retaining archived proofs."""
        res = self.client.post("/api/v1/internal-pings/cleanup-expired?retention_days=90", headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("purged_count", data)
        self.assertIn("retained_proofs_count", data)
        self.assertGreaterEqual(data["retained_proofs_count"], 1)

    def test_06_get_row_thread(self):
        """Verify getting chat and ping thread for a specific operational row."""
        res = self.client.get("/api/v1/internal-pings/row-thread?context_type=TASK&context_id=TSK-102")
        self.assertEqual(res.status_code, 200)
        pings = res.json()["data"]
        self.assertIsInstance(pings, list)
        self.assertGreaterEqual(len(pings), 1)
        self.assertEqual(pings[0]["context_id"], "TSK-102")

    def test_07_resolve_assigned_agent_and_accountant(self):
        """Verify resolving assigned broker and accountant dynamically."""
        # 1. Resolve ASSIGNED_AGENT for res-28
        payload = {
            "recipient_role": "ASSIGNED_AGENT",
            "context_type": "RESERVATION_DEPOSIT",
            "context_id": "res-28",
            "context_snapshot": {
                "rowId": "res-28",
                "title": "عربون حجز وحدة #Unit-5-57-1",
                "assignedUser": "Ibrahim Alnemari"
            },
            "message_text": "متابعة الحجز والعميل",
            "urgency_level": "NORMAL",
            "is_archived": False
        }
        res = self.client.post("/api/v1/internal-pings", json=payload, headers={"X-User-ID": "user-51"})
        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertEqual(data["recipient_name"], "Ibrahim Alnemari")
        self.assertEqual(data["recipient_user_id"], "user-43")

        # 2. Resolve ACCOUNTANT
        payload_acc = {
            "recipient_role": "ACCOUNTANT",
            "context_type": "RESERVATION_DEPOSIT",
            "context_id": "res-28",
            "context_snapshot": {"amount": "22,500.00 SAR"},
            "message_text": "متابعة سند القبض",
            "urgency_level": "NORMAL",
            "is_archived": False
        }
        res_acc = self.client.post("/api/v1/internal-pings", json=payload_acc, headers={"X-User-ID": "user-51"})
        self.assertEqual(res_acc.status_code, 201)
        data_acc = res_acc.json()["data"]
        self.assertEqual(data_acc["recipient_role"], "ACCOUNTANT")
        self.assertEqual(data_acc["recipient_user_id"], "user-19")
        self.assertEqual(data_acc["recipient_name"], "Demo Agent 26")

