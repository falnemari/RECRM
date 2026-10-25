import unittest
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.services.calculation_service import CalculationService

class TestAgentCompensationAndGovFees(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    def test_salaried_employee_commission_is_zero_and_exempt(self):
        """
        Verify salaried employee receives 0 deal commission,
        and is marked EXEMPT_SALARY while logging the office net brokerage.
        """
        agent_profile = {
            "compensation_type": "SALARY",
            "base_salary": 8500.0,
            "sales_commission_rate": 0.0,
            "rent_commission_rate": 0.0,
            "sales_fixed_cut": 0.0,
            "rent_fixed_cut": 0.0,
        }
        res = CalculationService.calculate_agent_commission(
            transaction_type="SALE",
            deal_value=1_000_000.0, # 1 Million SAR Sale
            brokerage_rate_percent=2.5,
            agent_profile=agent_profile
        )

        # RETT 5% (50,000 SAR) and 15% VAT on brokerage (3,750 SAR) are excluded
        self.assertEqual(res["gross_deal_value"], 1_000_000.0)
        self.assertEqual(res["gross_brokerage_amount"], 25_000.0)
        self.assertEqual(res["gov_fees_deducted"], 3_750.0) # 15% VAT excluded
        self.assertEqual(res["statutory_pass_through_tax"], 50_000.0) # 5% RETT excluded
        self.assertEqual(res["net_commission_base"], 25_000.0)
        
        # Salaried agent MUST get 0.00 SAR
        self.assertEqual(res["amount"], 0.0)
        self.assertEqual(res["rate"], 0.0)
        self.assertEqual(res["status"], "EXEMPT_SALARY")
        self.assertIn("معفى من عمولة الصفقات الفردية", res["calculation_notes"])

    def test_commission_split_agent_calculated_strictly_on_net_brokerage(self):
        """
        Verify commission split agent receives exact percentage of NET brokerage,
        never on gross transaction value, and never including VAT or government fees.
        """
        agent_profile = {
            "compensation_type": "COMMISSION",
            "base_salary": 0.0,
            "sales_commission_rate": 30.0, # 30% of Net Brokerage
            "rent_commission_rate": 25.0,
        }
        res = CalculationService.calculate_agent_commission(
            transaction_type="SALE",
            deal_value=1_000_000.0,
            brokerage_rate_percent=2.5,
            agent_profile=agent_profile
        )

        self.assertEqual(res["net_commission_base"], 25_000.0)
        # Agent gets 30% of 25,000 = 7,500 SAR
        self.assertEqual(res["amount"], 7_500.0)
        self.assertEqual(res["rate"], 30.0)
        self.assertEqual(res["status"], "PENDING")
        self.assertEqual(res["gov_fees_deducted"], 3_750.0)
        self.assertIn("30.0%", res["calculation_notes"])

    def test_fixed_cut_agent_receives_exact_lump_sum(self):
        """
        Verify agent on fixed cut receives flat fee per closed deal.
        """
        agent_profile = {
            "compensation_type": "FIXED_CUT",
            "base_salary": 0.0,
            "sales_fixed_cut": 2_500.0,
            "rent_fixed_cut": 800.0,
        }
        res_sale = CalculationService.calculate_agent_commission(
            transaction_type="SALE",
            deal_value=800_000.0,
            brokerage_rate_percent=2.5, # 20,000 SAR net brokerage
            agent_profile=agent_profile
        )
        self.assertEqual(res_sale["amount"], 2_500.0)
        self.assertEqual(res_sale["status"], "PENDING")
        self.assertEqual(res_sale["compensation_type"], "FIXED_CUT")

        res_rent = CalculationService.calculate_agent_commission(
            transaction_type="RENT",
            deal_value=60_000.0,
            brokerage_rate_percent=2.5, # 1,500 SAR net brokerage
            agent_profile=agent_profile
        )
        self.assertEqual(res_rent["amount"], 800.0)
        self.assertEqual(res_rent["status"], "PENDING")
        self.assertEqual(res_rent["compensation_type"], "FIXED_CUT")

    def test_hybrid_agent_compensation(self):
        """
        Verify hybrid agent (salary + incentive percentage).
        """
        agent_profile = {
            "compensation_type": "SALARY_PLUS_COMMISSION",
            "base_salary": 4000.0,
            "sales_commission_rate": 15.0, # 15% incentive
            "rent_commission_rate": 10.0,
        }
        res = CalculationService.calculate_agent_commission(
            transaction_type="SALE",
            deal_value=500_000.0, # Net brokerage 2.5% = 12,500 SAR
            agent_profile=agent_profile
        )
        # 15% of 12,500 = 1,875.0 SAR
        self.assertEqual(res["amount"], 1_875.0)
        self.assertEqual(res["rate"], 15.0)
        self.assertEqual(res["status"], "PENDING")

    def test_calculation_api_endpoint(self):
        """
        Verify /api/v1/calculations/agent-commission endpoint.
        """
        payload = {
            "transaction_type": "SALE",
            "deal_value": 2_000_000.0,
            "brokerage_rate_percent": 2.5,
            "compensation_type": "COMMISSION",
            "sales_commission_rate": 35.0
        }
        response = self.client.post("/api/v1/calculations/agent-commission", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        # Gross brokerage: 50,000 SAR -> Net base: 50,000 SAR -> 35% = 17,500 SAR
        self.assertEqual(data["gross_deal_value"], 2_000_000.0)
        self.assertEqual(data["gross_brokerage_amount"], 50_000.0)
        self.assertEqual(data["amount"], 17_500.0)
        self.assertEqual(data["gov_fees_deducted"], 7_500.0)

    def test_admin_users_api_returns_compensation_profile(self):
        """
        Verify /api/v1/admin/users lists compensation profile columns.
        """
        response = self.client.get("/api/v1/admin/users?page_size=5")
        self.assertEqual(response.status_code, 200)
        users = response.json()["data"]
        self.assertTrue(len(users) > 0)
        for u in users:
            self.assertIn("compensation_type", u)
            self.assertIn("base_salary", u)
            self.assertIn("sales_commission_rate", u)
            self.assertIn("sales_fixed_cut", u)

    def test_commissions_api_returns_breakdown_and_gov_fees(self):
        """
        Verify /api/v1/commissions endpoint returns enriched financial audit columns.
        """
        response = self.client.get("/api/v1/commissions?page_size=5")
        self.assertEqual(response.status_code, 200)
        commissions = response.json()["data"]
        self.assertTrue(len(commissions) > 0)
        for c in commissions:
            self.assertIn("compensation_type", c)
            self.assertIn("gross_deal_value", c)
            self.assertIn("gross_brokerage_amount", c)
            self.assertIn("gov_fees_deducted", c)
            self.assertIn("net_commission_base", c)
            self.assertIn("calculation_notes", c)

if __name__ == "__main__":
    unittest.main()
