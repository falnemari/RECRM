import unittest
import asyncpg
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

class TestPropertiesAndInventory(unittest.IsolatedAsyncioTestCase):
    async def test_01_create_project_and_building_lifecycle(self):
        """
        Verify POST /api/v1/projects and POST /api/v1/buildings succeed with valid JSON
        and sequential IDs without sequence desynchronization or JSON.parse errors.
        """
        with TestClient(app) as client:
            # 1. Create Project
            proj_payload = {
                "name_ar": "مشروع اختبار الآلية",
                "name_en": "Mechanism Test Project",
                "status": "ACTIVE"
            }
            res = client.post("/api/v1/projects", json=proj_payload)
            self.assertEqual(res.status_code, 201, f"Expected 201, got {res.status_code}: {res.text}")
            json_data = res.json()
            self.assertIn("data", json_data)
            project = json_data["data"]
            project_id = project["project_id"]
            self.assertTrue(project_id.startswith("project-"))
            self.assertEqual(project["name_ar"], "مشروع اختبار الآلية")

            # 2. Create Building under this Project
            bld_payload = {
                "project_id": project_id,
                "building_code": "BLD-TEST-AUTO-01",
                "name": "برج الاختبار الآلي",
                "floors_count": 10
            }
            bld_res = client.post("/api/v1/buildings", json=bld_payload)
            self.assertEqual(bld_res.status_code, 201, f"Expected 201, got {bld_res.status_code}: {bld_res.text}")
            bld_json = bld_res.json()
            self.assertIn("data", bld_json)
            building = bld_json["data"]
            building_id = building["building_id"]
            self.assertTrue(building_id.startswith("building-"))

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM buildings WHERE building_id = $1", building_id)
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()

    async def test_02_create_land_unit_without_building(self):
        """
        Verify real estate unit (e.g. Land / Plot) can be created directly under a Project
        without requiring a Building (building_id = None), and filtered by project_id.
        """
        with TestClient(app) as client:
            # 1. Create a Project
            proj_payload = {
                "name_ar": "مخطط الأراضي السكنية",
                "name_en": "Residential Lands Master Plan",
                "status": "ACTIVE"
            }
            res = client.post("/api/v1/projects", json=proj_payload)
            self.assertEqual(res.status_code, 201)
            project_id = res.json()["data"]["project_id"]

            # 2. Create a Land Unit (Plot) without a building
            unit_payload = {
                "project_id": project_id,
                "building_id": None,
                "unit_number": "PLOT-A-101",
                "property_type_id": "property_type-10",  # أرض / LAND
                "area_sqm": 650.0,
                "asking_price": 1200000.0,
                "status": "AVAILABLE"
            }
            unit_res = client.post("/api/v1/units", json=unit_payload)
            self.assertEqual(unit_res.status_code, 201, f"Failed to create land unit: {unit_res.text}")
            unit_data = unit_res.json()["data"]
            unit_id = unit_data["unit_id"]

            self.assertTrue(unit_id.startswith("unit-"))
            self.assertIsNone(unit_data["building_id"])
            self.assertEqual(unit_data["project_id"], project_id)
            self.assertEqual(unit_data["unit_number"], "PLOT-A-101")
            self.assertEqual(unit_data["property_type_id"], "property_type-10")
            self.assertEqual(unit_data["area_sqm"], 650.0)

            # 3. Duplicate check within same project without building
            dup_res = client.post("/api/v1/units", json=unit_payload)
            self.assertEqual(dup_res.status_code, 409)

            # 4. Fetch unit details by ID
            get_res = client.get(f"/api/v1/units/{unit_id}")
            self.assertEqual(get_res.status_code, 200)
            self.assertIsNone(get_res.json()["data"]["building_id"])
            self.assertEqual(get_res.json()["data"]["project_id"], project_id)
            self.assertEqual(get_res.json()["data"]["project_name_ar"], "مخطط الأراضي السكنية")

            # 5. List units filtered by project_id
            list_res = client.get(f"/api/v1/units?project_id={project_id}")
            self.assertEqual(list_res.status_code, 200)
            items = list_res.json()["data"]
            self.assertTrue(any(item["unit_id"] == unit_id for item in items))

            # 6. Update the Land unit
            upd_res = client.put(f"/api/v1/units/{unit_id}", json={
                "asking_price": 1250000.0,
                "unit_number": "PLOT-A-101-UPDATED"
            })
            self.assertEqual(upd_res.status_code, 200)
            self.assertEqual(upd_res.json()["data"]["asking_price"], 1250000.0)
            self.assertEqual(upd_res.json()["data"]["unit_number"], "PLOT-A-101-UPDATED")

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()

    async def test_03_unit_listing_purpose_and_eligibility(self):
        """
        Verify units can be classified by listing_purpose (SALE, RENT, INVESTMENT, ALL),
        filtered by API query, and strictly matched with customer inquiry_type.
        """
        from app.services.calculation_service import CalculationService

        with TestClient(app) as client:
            # 1. Create a project
            proj_res = client.post("/api/v1/projects", json={
                "name_ar": "مشروع اختبار أغراض الوحدات",
                "name_en": "Listing Purpose Test Project",
                "status": "ACTIVE"
            })
            self.assertEqual(proj_res.status_code, 201)
            project_id = proj_res.json()["data"]["project_id"]

            # 2. Create SALE unit
            sale_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "unit_number": "PURPOSE-SALE-01",
                "asking_price": 950000.0,
                "listing_purpose": "SALE",
                "status": "AVAILABLE"
            })
            self.assertEqual(sale_res.status_code, 201)
            sale_unit = sale_res.json()["data"]
            self.assertEqual(sale_unit["listing_purpose"], "SALE")

            # 3. Create RENT unit
            rent_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "unit_number": "PURPOSE-RENT-01",
                "rent_price": 45000.0,
                "listing_purpose": "RENT",
                "status": "AVAILABLE"
            })
            self.assertEqual(rent_res.status_code, 201)
            rent_unit = rent_res.json()["data"]
            self.assertEqual(rent_unit["listing_purpose"], "RENT")

            # 4. Filter by listing_purpose = RENT
            get_rent = client.get(f"/api/v1/units?project_id={project_id}&listing_purpose=RENT")
            self.assertEqual(get_rent.status_code, 200)
            rent_items = get_rent.json()["data"]
            self.assertTrue(any(u["unit_id"] == rent_unit["unit_id"] for u in rent_items))
            self.assertFalse(any(u["unit_id"] == sale_unit["unit_id"] for u in rent_items), "SALE unit must not appear in RENT filter")

            # 5. Filter by listing_purpose = SALE
            get_sale = client.get(f"/api/v1/units?project_id={project_id}&listing_purpose=SALE")
            self.assertEqual(get_sale.status_code, 200)
            sale_items = get_sale.json()["data"]
            self.assertTrue(any(u["unit_id"] == sale_unit["unit_id"] for u in sale_items))
            self.assertFalse(any(u["unit_id"] == rent_unit["unit_id"] for u in sale_items), "RENT unit must not appear in SALE filter")

            # 6. Test CalculationService eligibility
            # Rental lead testing a SALE unit -> Must be INELIGIBLE
            is_ok_sale_for_rent, _ = CalculationService.check_property_eligibility(
                unit_status="AVAILABLE",
                property_amount=45000.0,
                budget_max=50000.0,
                inquiry_type="RENT",
                unit_listing_purpose="SALE"
            )
            self.assertFalse(is_ok_sale_for_rent, "Sale unit must not be eligible for a RENT lead")

            # Rental lead testing a RENT unit -> Must be ELIGIBLE
            is_ok_rent_for_rent, _ = CalculationService.check_property_eligibility(
                unit_status="AVAILABLE",
                property_amount=45000.0,
                budget_max=50000.0,
                inquiry_type="RENT",
                unit_listing_purpose="RENT"
            )
            self.assertTrue(is_ok_rent_for_rent, "Rent unit must be eligible for a RENT lead")

            # Buyer lead testing a RENT unit -> Must be INELIGIBLE
            is_ok_rent_for_buy, _ = CalculationService.check_property_eligibility(
                unit_status="AVAILABLE",
                property_amount=950000.0,
                budget_max=1000000.0,
                inquiry_type="BUY",
                unit_listing_purpose="RENT"
            )
            self.assertFalse(is_ok_rent_for_buy, "Rent unit must not be eligible for a BUY lead")

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM units WHERE unit_id IN ($1, $2)", sale_unit["unit_id"], rent_unit["unit_id"])
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()

    async def test_04_investment_unit_metrics_and_persistence(self):
        """
        Verify real estate unit created or updated with investment parameters
        (annual_operating_expenses, annual_vacancy_rate, investment_notes)
        persists accurately and returns in API responses without artificial defaults.
        """
        with TestClient(app) as client:
            proj_res = client.post("/api/v1/projects", json={
                "name_ar": "مشروع أبراج الاستثمار",
                "name_en": "Investment Towers Project",
                "status": "ACTIVE"
            })
            self.assertEqual(proj_res.status_code, 201)
            project_id = proj_res.json()["data"]["project_id"]

            unit_payload = {
                "project_id": project_id,
                "unit_number": "INV-OFFICE-801",
                "property_type_id": "property_type-10",
                "area_sqm": 280.0,
                "asking_price": 2500000.0,
                "rent_price": 220000.0,
                "annual_operating_expenses": 25000.0,
                "annual_vacancy_rate": 5.0,
                "investment_notes": "مؤجر بعقد سنوي موثق حتى 2028 - تدفقات نقدية مستقرة",
                "listing_purpose": "INVESTMENT",
                "status": "AVAILABLE"
            }
            res = client.post("/api/v1/units", json=unit_payload)
            self.assertEqual(res.status_code, 201, f"Failed to create investment unit: {res.text}")
            u_data = res.json()["data"]
            unit_id = u_data["unit_id"]

            self.assertEqual(u_data["asking_price"], 2500000.0)
            self.assertEqual(u_data["rent_price"], 220000.0)
            self.assertEqual(u_data["annual_operating_expenses"], 25000.0)
            self.assertEqual(u_data["annual_vacancy_rate"], 5.0)
            self.assertEqual(u_data["investment_notes"], "مؤجر بعقد سنوي موثق حتى 2028 - تدفقات نقدية مستقرة")

            # Update unit via PUT
            update_payload = {
                "annual_operating_expenses": 28000.0,
                "annual_vacancy_rate": 4.0
            }
            put_res = client.put(f"/api/v1/units/{unit_id}", json=update_payload)
            self.assertEqual(put_res.status_code, 200)
            upd_data = put_res.json()["data"]
            self.assertEqual(upd_data["annual_operating_expenses"], 28000.0)
            self.assertEqual(upd_data["annual_vacancy_rate"], 4.0)

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()

