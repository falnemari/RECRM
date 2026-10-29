import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestTaskRowSelectionAndWorkflowInsertion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_task_row_selection_and_workflow_insertion(self):
        # 1. Fetch existing leads
        leads_resp = self.client.get("/api/v1/leads?page_size=10")
        self.assertEqual(leads_resp.status_code, 200)
        leads_data = leads_resp.json()["data"]
        self.assertTrue(len(leads_data) > 0)
        lead = leads_data[0]
        lead_id = lead["lead_id"]

        # 2. Get existing tasks list and verify the new fields are returned
        tasks_resp = self.client.get("/api/v1/tasks?page_size=10")
        self.assertEqual(tasks_resp.status_code, 200)
        tasks = tasks_resp.json()["data"]
        self.assertTrue(len(tasks) > 0)
        sample_task = tasks[0]
        self.assertIn("parent_task_id", sample_task)
        self.assertIn("lead_budget_max", sample_task)
        self.assertIn("opp_expected_value", sample_task)
        self.assertIn("opp_stage", sample_task)

        parent_task_id = None
        adhoc_task_id = None
        try:
            # 3. Create a parent task for the lead
            parent_payload = {
                "title": "مهمة رئيسية للاختبار — فحص المعاملة",
                "priority": "HIGH",
                "lead_id": lead_id,
                "template_id": "TASK_LEAD_FOLLOWUP"
            }
            create_parent_resp = self.client.post("/api/v1/tasks", json=parent_payload)
            self.assertEqual(create_parent_resp.status_code, 201)
            parent_task = create_parent_resp.json()["data"]
            parent_task_id = parent_task["task_id"]
            self.assertEqual(parent_task["lead_id"], lead_id)

            # 4. Insert an ad-hoc best practice task referencing the parent task
            adhoc_payload = {
                "title": "الاستثمار — التفاوض على التعديل السعري وعيوب الفحص (CapEx)",
                "template_id": "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
                "lead_id": lead_id,
                "parent_task_id": parent_task_id,
                "priority": parent_task["priority"]
            }
            create_adhoc_resp = self.client.post("/api/v1/tasks", json=adhoc_payload)
            self.assertEqual(create_adhoc_resp.status_code, 201)
            adhoc_task = create_adhoc_resp.json()["data"]
            adhoc_task_id = adhoc_task["task_id"]
            self.assertEqual(adhoc_task["parent_task_id"], parent_task_id)
            self.assertEqual(adhoc_task["template_id"], "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT")

            # 5. Fetch the newly created task and verify parent_task_id persistence
            fetch_resp = self.client.get(f"/api/v1/tasks/{adhoc_task['task_id']}")
            self.assertEqual(fetch_resp.status_code, 200)
            fetched_task = fetch_resp.json()["data"]
            self.assertEqual(fetched_task["parent_task_id"], parent_task_id)
            self.assertEqual(fetched_task["lead_id"], lead_id)
        finally:
            # Clean up test-created tasks to ensure idempotency and prevent DB clutter
            if adhoc_task_id or parent_task_id:
                import asyncio, asyncpg
                from app.config import settings
                async def _cleanup_tasks():
                    conn = await asyncpg.connect(settings.asyncpg_dsn)
                    if adhoc_task_id:
                        await conn.execute("DELETE FROM tasks WHERE task_id = $1", adhoc_task_id)
                    if parent_task_id:
                        await conn.execute("DELETE FROM tasks WHERE task_id = $1", parent_task_id)
                    await conn.close()
                asyncio.run(_cleanup_tasks())

    def test_ui_contains_task_row_selection_and_requirements(self):
        with open("src/ui/tasks.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        # Verify UI elements for row highlighting & context recognition
        self.assertIn("selected-task-row", html_content)
        self.assertIn("selected-task-banner", html_content)
        self.assertIn("selectTaskRow", html_content)
        self.assertIn("insertTaskForSelectedRow", html_content)
        self.assertIn("modal-task-context-card", html_content)
        self.assertIn("getTaskRequirementsSpecs", html_content)
        self.assertIn("task-parent-id", html_content)
        self.assertIn("TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT", html_content)

