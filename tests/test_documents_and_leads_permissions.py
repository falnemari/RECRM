import unittest
from datetime import date
from fastapi.testclient import TestClient
from app.main import app

class TestDocumentsAndLeadsPermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    # -------------------------------------------------------------
    # 1. Document Update & Delete Permissions
    # -------------------------------------------------------------
    def test_document_permissions_gm_can_edit_and_delete(self):
        # Create a document as GM (user-51)
        res_create = self.client.post(
            "/api/v1/documents",
            json={
                "file_name": "Test_Deed_For_Permissions.pdf",
                "document_type_code": "TITLE_DEED",
                "status": "ACTIVE",
                "notes": "Initial note"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_create.status_code, 201)
        doc_id = res_create.json()["data"]["document_id"]

        # GM updates the document -> Allowed (200)
        res_update = self.client.put(
            f"/api/v1/documents/{doc_id}",
            json={
                "file_name": "Test_Deed_For_Permissions_Updated.pdf",
                "notes": "Updated by General Manager"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.json()["data"]["file_name"], "Test_Deed_For_Permissions_Updated.pdf")
        self.assertEqual(res_update.json()["data"]["notes"], "Updated by General Manager")

        # Branch Manager (user-5 Makkah) tries to DELETE -> 403 Forbidden (restricted to GM only)
        res_bm_del = self.client.delete(
            f"/api/v1/documents/{doc_id}",
            headers={"X-User-ID": "user-5"}
        )
        self.assertEqual(res_bm_del.status_code, 403)
        self.assertIn("محصورة بالمدير العام", res_bm_del.json()["detail"])

        # Agent (user-43) tries to DELETE -> 403 Forbidden
        res_ag_del = self.client.delete(
            f"/api/v1/documents/{doc_id}",
            headers={"X-User-ID": "user-43"}
        )
        self.assertEqual(res_ag_del.status_code, 403)

        # GM deletes the document -> Allowed (200)
        res_gm_del = self.client.delete(
            f"/api/v1/documents/{doc_id}",
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_gm_del.status_code, 200)
        self.assertTrue(res_gm_del.json()["data"]["deleted"])

    def test_document_branch_manager_can_edit_own_branch_inventory_only(self):
        # 1. Create a document linked to a unit in Makkah (e.g. Unit-5-57-1 or similar)
        # Find a unit in Makkah (city-10)
        res_units = self.client.get("/api/v1/units?city_id=city-10&page_size=1")
        makkah_units = res_units.json()["data"]
        self.assertTrue(len(makkah_units) > 0, "Expected at least one Makkah unit")
        makkah_unit_id = makkah_units[0]["unit_id"]

        # Create doc for Makkah unit
        res_doc_makkah = self.client.post(
            "/api/v1/documents",
            json={
                "file_name": "Makkah_Unit_Doc.pdf",
                "document_type_code": "TITLE_DEED",
                "unit_id": makkah_unit_id,
                "status": "ACTIVE"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_doc_makkah.status_code, 201)
        makkah_doc_id = res_doc_makkah.json()["data"]["document_id"]

        # Find a unit in Riyadh (city-5)
        res_riyadh_units = self.client.get("/api/v1/units?city_id=city-5&page_size=1")
        riyadh_units = res_riyadh_units.json()["data"]
        self.assertTrue(len(riyadh_units) > 0, "Expected at least one Riyadh unit")
        riyadh_unit_id = riyadh_units[0]["unit_id"]

        res_doc_riyadh = self.client.post(
            "/api/v1/documents",
            json={
                "file_name": "Riyadh_Unit_Doc.pdf",
                "document_type_code": "TITLE_DEED",
                "unit_id": riyadh_unit_id,
                "status": "ACTIVE"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_doc_riyadh.status_code, 201)
        riyadh_doc_id = res_doc_riyadh.json()["data"]["document_id"]

        # User-5 is Makkah Branch Manager (branch-4)
        # Makkah BM updates Makkah unit doc -> Allowed (200)
        res_edit_makkah = self.client.put(
            f"/api/v1/documents/{makkah_doc_id}",
            json={"notes": "Updated by Makkah BM"},
            headers={"X-User-ID": "user-5"}
        )
        self.assertEqual(res_edit_makkah.status_code, 200)

        # Makkah BM updates Riyadh unit doc -> 403 Forbidden
        res_edit_riyadh = self.client.put(
            f"/api/v1/documents/{riyadh_doc_id}",
            json={"notes": "Unauthorized BM edit"},
            headers={"X-User-ID": "user-5"}
        )
        self.assertEqual(res_edit_riyadh.status_code, 403)
        self.assertIn("لا تملك صلاحية تعديل هذا المستند", res_edit_riyadh.json()["detail"])

        # Clean up created docs with GM
        self.client.delete(f"/api/v1/documents/{makkah_doc_id}", headers={"X-User-ID": "user-51"})
        self.client.delete(f"/api/v1/documents/{riyadh_doc_id}", headers={"X-User-ID": "user-51"})

    # -------------------------------------------------------------
    # 2. Broker / Agent Scoping
    # -------------------------------------------------------------
    def test_users_scoping_branch_manager_vs_gm(self):
        # When GM (user-51) queries /users -> returns all users across all branches
        res_gm = self.client.get("/api/v1/users", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_gm.status_code, 200)
        gm_users = res_gm.json()["data"]
        branch_ids_gm = set(u.get("branch_id") for u in gm_users if u.get("branch_id"))
        self.assertGreater(len(branch_ids_gm), 1, "GM must see users from multiple branches")

        # When Makkah BM (user-5, branch-4) queries /users -> automatically scoped to branch-4 only
        res_bm = self.client.get("/api/v1/users", headers={"X-User-ID": "user-5"})
        self.assertEqual(res_bm.status_code, 200)
        bm_users = res_bm.json()["data"]
        for u in bm_users:
            if u.get("branch_id"):
                self.assertEqual(u["branch_id"], "branch-4", "Branch Manager must only see users from their own branch")

    # -------------------------------------------------------------
    # 3. Lead Deletion & Permissions
    # -------------------------------------------------------------
    def test_lead_deletion_permissions_and_cascade(self):
        # Create a lead in Makkah (branch-4)
        res_lead = self.client.post(
            "/api/v1/leads",
            json={
                "customer_id": "customer-21",
                "inquiry_type": "BUY",
                "preferred_city_id": "city-10",
                "priority": "HIGH",
                "status": "QUALIFIED"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_lead.status_code, 201)
        lead_id = res_lead.json()["data"]["lead_id"]

        # Add a note and a task to this lead
        res_note = self.client.post(
            f"/api/v1/leads/{lead_id}/notes",
            json={"note": "Test note for deletion cascade"}
        )
        self.assertEqual(res_note.status_code, 201)

        # Sales Agent (user-43) tries to DELETE -> 403 Forbidden
        res_ag_del = self.client.delete(
            f"/api/v1/leads/{lead_id}",
            headers={"X-User-ID": "user-43"}
        )
        self.assertEqual(res_ag_del.status_code, 403)
        self.assertIn("محصورة بمدراء الفروع والمدير العام", res_ag_del.json()["detail"])

        # Makkah BM (user-5) deletes Makkah lead -> Allowed (200)
        res_bm_del = self.client.delete(
            f"/api/v1/leads/{lead_id}",
            headers={"X-User-ID": "user-5"}
        )
        self.assertEqual(res_bm_del.status_code, 200)
        self.assertTrue(res_bm_del.json()["data"]["deleted"])

        # Verify lead no longer exists
        res_get = self.client.get(f"/api/v1/leads/{lead_id}")
        self.assertEqual(res_get.status_code, 404)

    def test_no_remaining_new_leads_in_database(self):
        # Verify creating and deleting a NEW lead cascades cleanly for managers
        res_lead = self.client.post(
            "/api/v1/leads",
            json={
                "customer_id": "customer-21",
                "inquiry_type": "BUY",
                "preferred_city_id": "city-10",
                "priority": "NORMAL",
                "status": "NEW"
            },
            headers={"X-User-ID": "user-51"}
        )
        self.assertEqual(res_lead.status_code, 201)
        lead_id = res_lead.json()["data"]["lead_id"]
        
        # GM deletes the NEW lead
        res_del = self.client.delete(f"/api/v1/leads/{lead_id}", headers={"X-User-ID": "user-51"})
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json()["data"]["deleted"])

if __name__ == "__main__":
    unittest.main()

