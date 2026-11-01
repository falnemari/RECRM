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

    async def test_05_project_and_building_directories_and_counts(self):
        """
        Verify Projects Directory and Buildings Directory endpoints:
        - GET /api/v1/projects supports search and returns accurate buildings_count and units_count.
        - GET /api/v1/buildings supports search and returns accurate units_count.
        """
        with TestClient(app) as client:
            # 1. Create Project
            proj_payload = {
                "name_ar": "مشروع دليل الأصول المتكامل",
                "name_en": "Integrated Directory Assets Project",
                "status": "ACTIVE"
            }
            res_p = client.post("/api/v1/projects", json=proj_payload)
            self.assertEqual(res_p.status_code, 201)
            project_id = res_p.json()["data"]["project_id"]

            # 2. Create 2 Buildings under this project
            bld1_payload = {
                "project_id": project_id,
                "building_code": "BLD-DIR-01",
                "name": "عمارة الدليل الأولى",
                "floors_count": 5
            }
            res_b1 = client.post("/api/v1/buildings", json=bld1_payload)
            self.assertEqual(res_b1.status_code, 201)
            bld1_id = res_b1.json()["data"]["building_id"]

            bld2_payload = {
                "project_id": project_id,
                "building_code": "BLD-DIR-02",
                "name": "عمارة الدليل الثانية",
                "floors_count": 8
            }
            res_b2 = client.post("/api/v1/buildings", json=bld2_payload)
            self.assertEqual(res_b2.status_code, 201)
            bld2_id = res_b2.json()["data"]["building_id"]

            # 3. Create 2 units in bld1, 1 unit in bld2
            u1_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": bld1_id,
                "unit_number": "DIR-U101",
                "status": "AVAILABLE"
            })
            self.assertEqual(u1_res.status_code, 201)
            u1_id = u1_res.json()["data"]["unit_id"]

            u2_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": bld1_id,
                "unit_number": "DIR-U102",
                "status": "AVAILABLE"
            })
            self.assertEqual(u2_res.status_code, 201)
            u2_id = u2_res.json()["data"]["unit_id"]

            u3_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": bld2_id,
                "unit_number": "DIR-U201",
                "status": "AVAILABLE"
            })
            self.assertEqual(u3_res.status_code, 201)
            u3_id = u3_res.json()["data"]["unit_id"]

            # 4. Test GET /api/v1/projects?search=...
            p_search_res = client.get(f"/api/v1/projects?search=الأصول المتكامل")
            self.assertEqual(p_search_res.status_code, 200)
            p_list = p_search_res.json()["data"]
            matched_p = next((p for p in p_list if p["project_id"] == project_id), None)
            self.assertIsNotNone(matched_p, "Created project should be found in search")
            self.assertEqual(matched_p["buildings_count"], 2, "Project should have 2 buildings")
            self.assertEqual(matched_p["units_count"], 3, "Project should have 3 units")

            # 5. Test GET /api/v1/buildings?search=...&project_id=...
            b_list_res = client.get(f"/api/v1/buildings?project_id={project_id}")
            self.assertEqual(b_list_res.status_code, 200)
            b_list = b_list_res.json()["data"]
            self.assertEqual(len(b_list), 2)

            bld1_found = next((b for b in b_list if b["building_id"] == bld1_id), None)
            self.assertIsNotNone(bld1_found)
            self.assertEqual(bld1_found["units_count"], 2)

            bld2_found = next((b for b in b_list if b["building_id"] == bld2_id), None)
            self.assertIsNotNone(bld2_found)
            self.assertEqual(bld2_found["units_count"], 1)

            # 6. Building search by code
            b_search_res = client.get(f"/api/v1/buildings?search=BLD-DIR-02")
            self.assertEqual(b_search_res.status_code, 200)
            b_search_data = b_search_res.json()["data"]
            self.assertTrue(any(b["building_id"] == bld2_id for b in b_search_data))

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM units WHERE unit_id IN ($1, $2, $3)", u1_id, u2_id, u3_id)
                await conn.execute("DELETE FROM buildings WHERE building_id IN ($1, $2)", bld1_id, bld2_id)
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()

    async def test_06_floor_no_and_total_floors_classification_and_hierarchy(self):
        """
        Verify:
        1. Buildings return the Project they belong to (project_id, project_name_ar, floors_count).
        2. Units in buildings return the Building (building_id, building_name) and floor_no (رقم الطابق)
           along with building_floors_count (عدد طوابق المبنى).
        3. Standalone assets (Villas, Duplexes, Townhouses, Buildings, Hotels) accept and return total_floors (عدد الطوابق).
        4. Units like Penthouses in buildings can record both floor_no and total_floors.
        """
        with TestClient(app) as client:
            # 1. Create Project
            p_res = client.post("/api/v1/projects", json={
                "name_ar": "مشروع تلال الرياض السكني",
                "name_en": "Riyadh Hills Residential Project",
                "status": "ACTIVE"
            })
            self.assertEqual(p_res.status_code, 201)
            project_id = p_res.json()["data"]["project_id"]

            # 2. Create Building under Project with floors_count = 12
            b_res = client.post("/api/v1/buildings", json={
                "project_id": project_id,
                "building_code": "TWR-HILLS-01",
                "name": "برج تلال النخبة",
                "floors_count": 12
            })
            self.assertEqual(b_res.status_code, 201)
            bld_data = b_res.json()["data"]
            building_id = bld_data["building_id"]
            self.assertEqual(bld_data["project_id"], project_id)
            self.assertEqual(bld_data["project_name_ar"], "مشروع تلال الرياض السكني")
            self.assertEqual(bld_data["floors_count"], 12)

            # 3. Create Apartment in Building with floor_no = 4
            apt_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": building_id,
                "unit_number": "APT-402",
                "property_type_id": "property_type-3",  # APARTMENTS / FLATS
                "floor_no": 4,
                "area_sqm": 160.0,
                "asking_price": 850000.0,
                "status": "AVAILABLE"
            })
            self.assertEqual(apt_res.status_code, 201)
            apt_data = apt_res.json()["data"]
            apt_id = apt_data["unit_id"]
            self.assertEqual(apt_data["building_id"], building_id)
            self.assertEqual(apt_data["building_name"], "برج تلال النخبة")
            self.assertEqual(apt_data["building_code"], "TWR-HILLS-01")
            self.assertEqual(apt_data["project_id"], project_id)
            self.assertEqual(apt_data["floor_no"], 4)
            self.assertEqual(apt_data["building_floors_count"], 12)

            # 4. Create Standalone Villa with total_floors = 3
            villa_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": None,
                "unit_number": "VILLA-HILLS-05",
                "property_type_id": "property_type-8",  # VILLA
                "total_floors": 3,
                "area_sqm": 420.0,
                "asking_price": 2800000.0,
                "status": "AVAILABLE"
            })
            self.assertEqual(villa_res.status_code, 201)
            villa_data = villa_res.json()["data"]
            villa_id = villa_data["unit_id"]
            self.assertIsNone(villa_data["building_id"])
            self.assertEqual(villa_data["project_id"], project_id)
            self.assertEqual(villa_data["total_floors"], 3)

            # 5. Create Penthouse in Building with both floor_no = 11 and total_floors = 2
            pent_res = client.post("/api/v1/units", json={
                "project_id": project_id,
                "building_id": building_id,
                "unit_number": "PENT-1101",
                "property_type_id": "property_type-1",  # PENTHOUSE
                "floor_no": 11,
                "total_floors": 2,
                "area_sqm": 350.0,
                "asking_price": 1950000.0,
                "status": "AVAILABLE"
            })
            self.assertEqual(pent_res.status_code, 201)
            pent_data = pent_res.json()["data"]
            pent_id = pent_data["unit_id"]
            self.assertEqual(pent_data["building_id"], building_id)
            self.assertEqual(pent_data["floor_no"], 11)
            self.assertEqual(pent_data["total_floors"], 2)
            self.assertEqual(pent_data["building_floors_count"], 12)

            # 6. Test Updating total_floors on Villa
            upd_res = client.put(f"/api/v1/units/{villa_id}", json={
                "total_floors": 2
            })
            self.assertEqual(upd_res.status_code, 200)
            self.assertEqual(upd_res.json()["data"]["total_floors"], 2)

            # Cleanup
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                await conn.execute("DELETE FROM units WHERE unit_id IN ($1, $2, $3)", apt_id, villa_id, pent_id)
                await conn.execute("DELETE FROM buildings WHERE building_id = $1", building_id)
                await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            finally:
                await conn.close()


