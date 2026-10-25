import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.services.calculation_service import CalculationService


class TestCalculationService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    # =========================================================================
    # 1. Budget Validity & Eligibility Tests (Section 3.A)
    # =========================================================================

    def test_rule1_budget_validity(self):
        # Valid: B_min <= B_max
        valid, err = CalculationService.validate_budget_range(500000, 800000)
        self.assertTrue(valid)
        self.assertIsNone(err)

        # Equal values are valid
        valid, err = CalculationService.validate_budget_range(500000, 500000)
        self.assertTrue(valid)

        # Invalid: B_min > B_max
        valid, err = CalculationService.validate_budget_range(900000, 800000)
        self.assertFalse(valid)
        self.assertIn("cannot exceed", err)

        # Negative amount
        valid, err = CalculationService.validate_budget_range(-100, 500000)
        self.assertFalse(valid)
        self.assertIn("cannot be negative", err)

    def test_rule2_budget_matching(self):
        # Rent matching: R_property <= B_rent,max
        self.assertTrue(CalculationService.check_budget_match(5000, 6000))
        self.assertTrue(CalculationService.check_budget_match(6000, 6000))
        self.assertFalse(CalculationService.check_budget_match(6500, 6000))

        # Purchase matching: P_property <= B_purchase,max
        self.assertTrue(CalculationService.check_budget_match(800000, 1000000))
        self.assertFalse(CalculationService.check_budget_match(1200000, 1000000))

    def test_rule3_property_eligibility(self):
        # Eligible unit: Available, within budget, matching location & bedrooms
        eligible, criteria = CalculationService.check_property_eligibility(
            unit_status="AVAILABLE",
            property_amount=750000,
            budget_max=800000,
            unit_city_id="city-1",
            preferred_city_id="city-1",
            unit_bedrooms=3,
            required_bedrooms_min=3,
            unit_area_sqm=180,
            required_area_min=150
        )
        self.assertTrue(eligible)
        self.assertTrue(criteria["available"])
        self.assertTrue(criteria["budget_match"])
        self.assertTrue(criteria["location_match"])
        self.assertTrue(criteria["requirements_match"])

        # Ineligible because unit is already RESERVED
        eligible, criteria = CalculationService.check_property_eligibility(
            unit_status="RESERVED",
            property_amount=750000,
            budget_max=800000
        )
        self.assertFalse(eligible)
        self.assertFalse(criteria["available"])

        # Ineligible because bedrooms < required (e.g. 2 bedrooms when 3 requested)
        eligible, criteria = CalculationService.check_property_eligibility(
            unit_status="AVAILABLE",
            property_amount=700000,
            budget_max=800000,
            unit_bedrooms=2,
            required_bedrooms_min=3
        )
        self.assertFalse(eligible)
        self.assertFalse(criteria["bedrooms_match"])

    def test_rule4_property_matching_score(self):
        # Calculate composite score with standard weights (30% budget, 25% location, 20% size, 10% amenities, 15% timing)
        eligible, score, breakdown = CalculationService.calculate_property_match_score(
            property_amount=800000,
            budget_min=600000,
            budget_max=850000,
            unit_city_id="city-1",
            preferred_city_id="city-1",
            unit_bedrooms=3,
            required_bedrooms_min=3,
            unit_area_sqm=200,
            required_area_min=180,
            is_available=True,
            amenities_match_ratio=1.0,
            timing_score=100.0
        )
        self.assertTrue(eligible)
        self.assertGreaterEqual(score, 80.0)
        self.assertLessEqual(score, 100.0)
        self.assertEqual(breakdown["weights"]["budget"], 0.30)
        self.assertEqual(breakdown["weights"]["location"], 0.25)

    # =========================================================================
    # 2. Document Specification Rental Formulas (Section 3.B)
    # =========================================================================

    def test_rental_metrics_document_example(self):
        """
        Verify exact illustrative numbers from Section 3.B:
        - Purchase price: SAR 800,000
        - Expected monthly rent: SAR 5,000
        - Annual vacancy allowance: SAR 3,000
        - Annual operating expenses: SAR 9,000
        - Acquisition costs: SAR 40,000
        Expected:
        - Annual gross rent: SAR 60,000
        - Effective annual rent: SAR 57,000
        - NOI: SAR 48,000
        - Gross yield: 7.50%
        - Net operating yield on SAR 840,000: 5.71%
        """
        res = CalculationService.calculate_rental_metrics(
            monthly_rent=5000.0,
            purchase_price=800000.0,
            annual_vacancy_allowance=3000.0,
            annual_operating_expenses=9000.0,
            acquisition_costs=40000.0
        )
        self.assertEqual(res["gross_annual_rent"], 60000.0)
        self.assertEqual(res["effective_annual_rent"], 57000.0)
        self.assertEqual(res["net_operating_income"], 48000.0)
        self.assertEqual(res["total_investment_basis"], 840000.0)
        self.assertEqual(res["gross_yield_percent"], 7.50)
        self.assertEqual(res["net_operating_yield_percent"], 5.71)

    # =========================================================================
    # 3. Investment Returns (Section 3.C)
    # =========================================================================

    def test_investment_returns(self):
        # 1. Cash-on-Cash Return:
        # Invested SAR 200,000, pre-tax annual cash flow SAR 24,000 -> 12.0% CoC
        # Purchase SAR 800,000, current value SAR 920,000 -> 15.0% appreciation
        # Sale proceeds SAR 900,000, rental flow SAR 40,000, initial invested SAR 200,000 -> 370% ROI
        returns = CalculationService.calculate_investment_returns(
            purchase_price=800000.0,
            cash_invested=200000.0,
            annual_pre_tax_cash_flow=24000.0,
            current_estimated_value=920000.0,
            net_sale_proceeds=900000.0,
            cumulative_rental_cash_flow=40000.0
        )
        self.assertEqual(returns["cash_on_cash_return_percent"], 12.0)
        self.assertEqual(returns["capital_appreciation_percent"], 15.0)
        self.assertEqual(returns["unrealized_gain"], 120000.0)
        self.assertEqual(returns["total_roi_percent"], 370.0)

    # =========================================================================
    # 4. Financial & Commission Controls (Section 3.E)
    # =========================================================================

    def test_outstanding_balance_controls(self):
        bal = CalculationService.calculate_outstanding_balance(amount_due=100000.0, amount_paid=25000.0)
        self.assertEqual(bal["outstanding_balance"], 75000.0)
        self.assertFalse(bal["is_fully_paid"])

        # Fully paid
        bal_full = CalculationService.calculate_outstanding_balance(amount_due=100000.0, amount_paid=100000.0)
        self.assertEqual(bal_full["outstanding_balance"], 0.0)
        self.assertTrue(bal_full["is_fully_paid"])

        # Error if amount_paid exceeds amount_due
        with self.assertRaises(ValueError):
            CalculationService.calculate_outstanding_balance(amount_due=50000.0, amount_paid=60000.0)

    def test_commission_document_example(self):
        # Document example: Commission base SAR 800,000 at 2% = SAR 16,000
        comm = CalculationService.calculate_commission(
            transaction_type="SALE",
            base_amount=800000.0,
            rate_percent=2.0
        )
        self.assertEqual(comm["commission_net"], 16000.0)
        self.assertEqual(comm["commission_gross"], 16000.0)

        # Rental fixed fee commission
        comm_rent = CalculationService.calculate_commission(
            transaction_type="RENT",
            base_amount=60000.0,
            rate_percent=5.0,
            fixed_fee=2500.0
        )
        self.assertEqual(comm_rent["commission_net"], 2500.0)

    # =========================================================================
    # 5. Managerial Performance KPIs (Section 7)
    # =========================================================================

    def test_managerial_kpis(self):
        # 1. First-contact SLA compliance %
        sla = CalculationService.calculate_sla_compliance_rate(
            leads_contacted_within_sla=45,
            eligible_leads_due=50
        )
        self.assertEqual(sla["sla_compliance_percent"], 90.0)

        # 2. Cohort conversion %
        conv = CalculationService.calculate_cohort_conversion_rate(
            successful_leads=12,
            total_qualified_leads_in_cohort=60
        )
        self.assertEqual(conv["conversion_rate_percent"], 20.0)

        # 3. Task completion rate %
        task_kpi = CalculationService.calculate_task_completion_rate(
            tasks_completed_on_time=85,
            tasks_due=100,
            tasks_overdue=15
        )
        self.assertEqual(task_kpi["on_time_completion_rate_percent"], 85.0)

        # 4. Viewing-to-offer conversion %
        view_conv = CalculationService.calculate_viewing_to_offer_conversion(
            offers_generated=8,
            eligible_completed_viewings=25
        )
        self.assertEqual(view_conv["viewing_to_offer_conversion_percent"], 32.0)

        # 5. Forecast versus actual rental variance
        var = CalculationService.calculate_forecast_rental_variance(
            actual_income=57000.0,
            forecast_income=60000.0
        )
        self.assertEqual(var["variance"], -3000.0)
        self.assertEqual(var["variance_percent"], -5.0)
        self.assertFalse(var["is_favorable"])

    # =========================================================================
    # 6. REST API Endpoints Verification (/api/v1/calculations)
    # =========================================================================

    def test_api_rental_metrics_endpoint(self):
        payload = {
            "monthly_rent": 5000.0,
            "purchase_price": 800000.0,
            "annual_vacancy_allowance": 3000.0,
            "annual_operating_expenses": 9000.0,
            "acquisition_costs": 40000.0
        }
        res = self.client.post("/api/v1/calculations/rental-metrics", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["gross_yield_percent"], 7.50)
        self.assertEqual(data["net_operating_yield_percent"], 5.71)
        self.assertEqual(data["net_operating_income"], 48000.0)

    def test_api_property_match_score_endpoint(self):
        payload = {
            "property_amount": 780000.0,
            "budget_min": 600000.0,
            "budget_max": 850000.0,
            "unit_city_id": "city-1",
            "preferred_city_id": "city-1",
            "unit_bedrooms": 3,
            "required_bedrooms_min": 3,
            "unit_area_sqm": 210.0,
            "required_area_min": 180.0
        }
        res = self.client.post("/api/v1/calculations/property-match-score", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["is_eligible"])
        self.assertGreaterEqual(data["total_score"], 80.0)

    def test_api_commission_endpoint(self):
        payload = {
            "transaction_type": "SALE",
            "base_amount": 800000.0,
            "rate_percent": 2.0,
            "tax_rate_percent": 15.0
        }
        res = self.client.post("/api/v1/calculations/commission", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["commission_net"], 16000.0)
        self.assertEqual(data["tax_amount"], 2400.0)
        self.assertEqual(data["commission_gross"], 18400.0)

    def test_estimate_technical_capex_and_adjustment(self):
        # Scenario 1: Clean/Excellent property, 5 years old, compliant
        res1 = CalculationService.estimate_technical_capex_and_adjustment(
            purchase_price=10_000_000.0,
            building_age_years=5,
            structural_condition="EXCELLENT",
            saudi_building_code_compliant=True,
            hvac_status="OPERATIONAL",
            elevators_status="OPERATIONAL",
            roofing_and_insulation_status="GOOD"
        )
        self.assertEqual(res1["estimated_capex_sar"], 0.0)
        self.assertEqual(res1["suggested_price_adjustment_sar"], 0.0)
        self.assertEqual(res1["adjusted_target_purchase_price_sar"], 10_000_000.0)

        # Scenario 2: Severe defects (CRITICAL structure, SBC non-compliant, faulty HVAC, inoperative elevator, leak, age 18)
        res2 = CalculationService.estimate_technical_capex_and_adjustment(
            purchase_price=10_000_000.0,
            building_age_years=18,
            structural_condition="CRITICAL",
            saudi_building_code_compliant=False,
            hvac_status="FAULTY",
            elevators_status="INOPERATIVE",
            roofing_and_insulation_status="WATER_LEAKAGE"
        )
        # Structural: 8% of 10M = 800,000
        # SBC: max(50k, 1.5% of 10M = 150k) = 150,000
        # HVAC: max(80k, 3.5% of 10M = 350k) = 350,000
        # Elevators: max(100k, 2% of 10M = 200k) = 200,000
        # Roofing: max(45k, 1.2% of 10M = 120k) = 120,000
        # Age: 10M * ((18-15)*0.003) = 10M * 0.009 = 90,000
        # Total = 800k + 150k + 350k + 200k + 120k + 90k = 1,710,000 SAR
        self.assertEqual(res2["estimated_capex_sar"], 1_710_000.0)
        self.assertEqual(res2["suggested_price_adjustment_sar"], 1_710_000.0)
        self.assertEqual(res2["adjusted_target_purchase_price_sar"], 8_290_000.0)

        # Scenario 3: Solvency Stress Test (lead-114 scenario: Price 12M, Max Budget 13M)
        # Moderate defects: FAIR structure (2.5% = 300k), age 10 (2*0.15% = 0.3% = 36k) -> CapEx = 336k
        res3 = CalculationService.estimate_technical_capex_and_adjustment(
            purchase_price=12_000_000.0,
            building_age_years=10,
            structural_condition="FAIR",
            saudi_building_code_compliant=True,
            hvac_status="OPERATIONAL",
            elevators_status="OPERATIONAL",
            roofing_and_insulation_status="GOOD",
            max_budget=13_000_000.0
        )
        self.assertEqual(res3["estimated_capex_sar"], 336_000.0)
        self.assertEqual(res3["worst_case_total_cost_sar"], 12_336_000.0)
        solv = res3["solvency_analysis"]
        self.assertIsNotNone(solv)
        self.assertEqual(solv["solvency_status"], "SOLVENT")
        self.assertEqual(solv["capital_buffer_sar"], 664_000.0)
        self.assertEqual(solv["negotiation_posture"], "SAFE_ABSORPTION")

        # Scenario 4: Solvency Stress Test with Deficit (Max Budget 12M < Worst Case 12.336M)
        res4 = CalculationService.estimate_technical_capex_and_adjustment(
            purchase_price=12_000_000.0,
            building_age_years=10,
            structural_condition="FAIR",
            max_budget=12_000_000.0
        )
        solv4 = res4["solvency_analysis"]
        self.assertEqual(solv4["solvency_status"], "DEFICIT")
        self.assertEqual(solv4["capital_buffer_sar"], -336_000.0)
        self.assertEqual(solv4["negotiation_posture"], "MANDATORY_DISCOUNT_CONTINGENCY")


if __name__ == "__main__":
    unittest.main()

