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

