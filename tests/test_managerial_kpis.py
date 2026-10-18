import unittest
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

from fastapi.testclient import TestClient
from app.main import app
from app.services.calculation_service import CalculationService


class TestManagerialKPIs(unittest.TestCase):
    """
    Test suite for Article 7: Equations for Managers and Team Performance.
    Validates Equations 7.1 to 7.5 math engine and the /reports/managerial-kpis API endpoint.
    """

    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    # =========================================================================
    # 1. Equation 7.1: Lead Contact SLA Compliance Rate
    # =========================================================================

    def test_eq_7_1_lead_sla_compliance_rate_normal(self):
        result = CalculationService.calculate_sla_compliance_rate(
            leads_contacted_within_sla=8,
            eligible_leads_due=10
        )
        self.assertEqual(result["leads_contacted_within_sla"], 8)
        self.assertEqual(result["eligible_leads_due"], 10)
        self.assertEqual(result["sla_compliance_percent"], 80.0)

    def test_eq_7_1_lead_sla_compliance_rate_zero_denominator(self):
        # When no leads are due, compliance is 100%
        result = CalculationService.calculate_sla_compliance_rate(
            leads_contacted_within_sla=0,
            eligible_leads_due=0
        )
        self.assertEqual(result["sla_compliance_percent"], 100.0)

    def test_eq_7_1_lead_sla_compliance_rate_zero_contacted(self):
        result = CalculationService.calculate_sla_compliance_rate(
            leads_contacted_within_sla=0,
            eligible_leads_due=5
        )
        self.assertEqual(result["sla_compliance_percent"], 0.0)

    # =========================================================================
    # 2. Equation 7.2: Cohort-based Lead-to-Transaction Conversion Rate
    # =========================================================================

    def test_eq_7_2_cohort_conversion_rate_normal(self):
        result = CalculationService.calculate_cohort_conversion_rate(
            successful_leads=3,
            total_qualified_leads_in_cohort=12
        )
        self.assertEqual(result["successful_leads"], 3)
        self.assertEqual(result["total_qualified_leads_in_cohort"], 12)
        self.assertEqual(result["conversion_rate_percent"], 25.0)

    def test_eq_7_2_cohort_conversion_rate_zero_denominator(self):
        result = CalculationService.calculate_cohort_conversion_rate(
            successful_leads=0,
            total_qualified_leads_in_cohort=0
        )
        self.assertEqual(result["conversion_rate_percent"], 0.0)

    # =========================================================================
    # 3. Equation 7.3: Task Completion Rate & Overdue Tasks
    # =========================================================================

    def test_eq_7_3_task_completion_rate_normal(self):
        result = CalculationService.calculate_task_completion_rate(
            tasks_completed_on_time=18,
            tasks_due=20,
            tasks_overdue=2
        )
        self.assertEqual(result["tasks_completed_on_time"], 18)
        self.assertEqual(result["tasks_due"], 20)
        self.assertEqual(result["tasks_overdue"], 2)
        self.assertEqual(result["on_time_completion_rate_percent"], 90.0)

    def test_eq_7_3_task_completion_rate_zero_due_no_overdue(self):
        result = CalculationService.calculate_task_completion_rate(
            tasks_completed_on_time=0,
            tasks_due=0,
            tasks_overdue=0
        )
        self.assertEqual(result["on_time_completion_rate_percent"], 100.0)

    def test_eq_7_3_task_completion_rate_zero_due_with_overdue(self):
        result = CalculationService.calculate_task_completion_rate(
            tasks_completed_on_time=0,
            tasks_due=0,
            tasks_overdue=3
        )
        self.assertEqual(result["on_time_completion_rate_percent"], 0.0)

    # =========================================================================
    # 4. Equation 7.4: Viewing-to-Offer Conversion Rate
    # =========================================================================

    def test_eq_7_4_viewing_to_offer_conversion_normal(self):
        result = CalculationService.calculate_viewing_to_offer_conversion(
            offers_generated=4,
            eligible_completed_viewings=10
        )
        self.assertEqual(result["offers_generated"], 4)
        self.assertEqual(result["eligible_completed_viewings"], 10)
        self.assertEqual(result["viewing_to_offer_conversion_percent"], 40.0)

    def test_eq_7_4_viewing_to_offer_conversion_zero_viewings(self):
        result = CalculationService.calculate_viewing_to_offer_conversion(
            offers_generated=0,
            eligible_completed_viewings=0
        )
        self.assertEqual(result["viewing_to_offer_conversion_percent"], 0.0)

    # =========================================================================
    # 5. Equation 7.5: Forecast versus Actual Rental Income Variance
    # =========================================================================

    def test_eq_7_5_rental_variance_favorable(self):
        result = CalculationService.calculate_forecast_rental_variance(
            actual_income=55000.0,
            forecast_income=50000.0
        )
        self.assertEqual(result["variance"], 5000.0)
        self.assertEqual(result["variance_percent"], 10.0)
        self.assertTrue(result["is_favorable"])

    def test_eq_7_5_rental_variance_unfavorable(self):
        result = CalculationService.calculate_forecast_rental_variance(
            actual_income=42000.0,
            forecast_income=50000.0
        )
        self.assertEqual(result["variance"], -8000.0)
        self.assertEqual(result["variance_percent"], -16.0)
        self.assertFalse(result["is_favorable"])

    def test_eq_7_5_rental_variance_zero_forecast(self):
        # Per Article 7: "If forecast income is zero, show the percentage variance as unavailable rather than dividing by zero."
        result = CalculationService.calculate_forecast_rental_variance(
            actual_income=12000.0,
            forecast_income=0.0
        )
        self.assertEqual(result["variance"], 12000.0)
        self.assertIsNone(result["variance_percent"])
        self.assertTrue(result["is_favorable"])

    # =========================================================================
    # 6. REST API Endpoint: GET /api/v1/reports/managerial-kpis
    # =========================================================================

    def test_api_managerial_kpis_endpoint_success(self):
        res = self.client.get(
            "/api/v1/reports/managerial-kpis",
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res.status_code, 200)
        json_data = res.json()
        self.assertIn("data", json_data)
        data = json_data["data"]

        # Validate all 5 equations exist in response payload
        self.assertIn("lead_sla_compliance", data)
        self.assertIn("sla_compliance_percent", data["lead_sla_compliance"])

        self.assertIn("lead_to_transaction_conversion", data)
        self.assertIn("conversion_rate_percent", data["lead_to_transaction_conversion"])

        self.assertIn("task_completion_rate", data)
        self.assertIn("on_time_completion_rate_percent", data["task_completion_rate"])
        self.assertIn("tasks_overdue", data["task_completion_rate"])

        self.assertIn("viewing_to_offer_conversion", data)
        self.assertIn("viewing_to_offer_conversion_percent", data["viewing_to_offer_conversion"])

        self.assertIn("forecast_vs_actual_rental_variance", data)
        self.assertIn("variance", data["forecast_vs_actual_rental_variance"])

        # Validate pipeline breakdown by purpose
        self.assertIn("pipeline_by_purpose", data)
        self.assertIsInstance(data["pipeline_by_purpose"], list)

        # Validate role perspective
        self.assertIn("role_perspective", data)
        self.assertTrue(data["role_perspective"]["is_manager"])

    def test_api_managerial_kpis_with_role_view_and_branch(self):
        res = self.client.get(
            "/api/v1/reports/managerial-kpis?role_view=SALES_AGENT&branch_id=branch-1",
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["role_perspective"]["active_role_view"], "SALES_AGENT")
        self.assertTrue(data["role_perspective"]["is_agent"])
        self.assertFalse(data["role_perspective"]["is_manager"])
        self.assertEqual(data["scope_info"]["branch_id"], "branch-1")


if __name__ == "__main__":
    unittest.main()

