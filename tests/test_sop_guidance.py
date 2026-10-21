import unittest
import urllib.parse
from fastapi.testclient import TestClient
from app.main import app

class TestSOPGuidance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_invest_confirm_objectives_guide(self):
        code = "TASK_INVEST_CONFIRM_OBJECTIVES"
        res = self.client.get(f"/api/v1/sop-guide/{urllib.parse.quote(code)}")
        self.assertEqual(res.status_code, 200)
        data = res.json().get("data", {})
        self.assertEqual(data.get("template_id"), "TASK_INVEST_CONFIRM_OBJECTIVES")
        self.assertIn("الاستثمار", data.get("stage_name_ar", ""))
        steps = data.get("execution_steps_ar", [])
        self.assertGreaterEqual(len(steps), 4)

    def test_invest_confirm_objectives_by_arabic_title(self):
        title = "الاستثمار — تأكيد الأهداف والميزانية"
        res = self.client.get(f"/api/v1/sop-guide/{urllib.parse.quote(title)}")
        self.assertEqual(res.status_code, 200)
        data = res.json().get("data", {})
        self.assertEqual(data.get("template_id"), "TASK_INVEST_CONFIRM_OBJECTIVES")
        steps = data.get("execution_steps_ar", [])
        self.assertGreaterEqual(len(steps), 4)

    def test_invest_activity_code_resolution(self):
        act_code = "ACT_INVEST_OBJECTIVES_CONFIRMED"
        res = self.client.get(f"/api/v1/sop-guide/{urllib.parse.quote(act_code)}")
        self.assertEqual(res.status_code, 200)
        data = res.json().get("data", {})
        self.assertEqual(data.get("template_id"), "TASK_INVEST_CONFIRM_OBJECTIVES")

    def test_rent_pipeline_guides(self):
        for code in ["TASK_RENT_LEAD_FIRST_CONTACT", "TASK_RENT_MATCH_PROPERTIES", "TASK_RENT_VIEWING_FOLLOW_UP", "TASK_RENT_PREPARE_TENANCY", "TASK_RENT_COLLECTION_MONITORING"]:
            res = self.client.get(f"/api/v1/sop-guide/{urllib.parse.quote(code)}")
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", {})
            self.assertEqual(data.get("template_id"), code)
            self.assertGreaterEqual(len(data.get("execution_steps_ar", [])), 4)

    def test_fallback_never_404(self):
        unknown_code = "UNKNOWN_CUSTOM_PROCEDURE_XYZ"
        res = self.client.get(f"/api/v1/sop-guide/{urllib.parse.quote(unknown_code)}")
        self.assertEqual(res.status_code, 200)
        data = res.json().get("data", {})
        self.assertIsNotNone(data)
        self.assertGreaterEqual(len(data.get("execution_steps_ar", [])), 4)

if __name__ == "__main__":
    unittest.main()

