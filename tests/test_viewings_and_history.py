import unittest
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

from fastapi.testclient import TestClient
from app.main import app


class TestViewingsAndViewingManagement(unittest.TestCase):

    def test_list_and_get_viewings(self):
        with TestClient(app) as client:
            # 1. List viewings
            res = client.get("/api/v1/viewings", headers={"X-User-ID": "user-1"})
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", [])
            self.assertIsInstance(data, list)

            # If any viewing exists, test single viewing fetch
            if len(data) > 0:
                v_id = data[0]["viewing_id"]
                res_single = client.get(f"/api/v1/viewings/{v_id}", headers={"X-User-ID": "user-1"})
                self.assertEqual(res_single.status_code, 200)
                single_v = res_single.json().get("data", {})
                self.assertEqual(single_v["viewing_id"], v_id)
                self.assertIn("status", single_v)
                self.assertIn("unit_number", single_v)

    def test_patch_viewing(self):
        with TestClient(app) as client:
            res = client.get("/api/v1/viewings", headers={"X-User-ID": "user-1"})
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", [])
            if len(data) > 0:
                v_id = data[0]["viewing_id"]
                original_notes = data[0].get("notes") or ""
                test_note = f"Updated via Test {os.urandom(4).hex()}"
                patch_res = client.patch(
                    f"/api/v1/viewings/{v_id}",
                    json={"notes": test_note, "status": "COMPLETED"},
                    headers={"X-User-ID": "user-1"}
                )
                self.assertEqual(patch_res.status_code, 200)
                updated_v = patch_res.json().get("data", {})
                self.assertEqual(updated_v["notes"], test_note)
                self.assertEqual(updated_v["status"], "COMPLETED")

                # Restore original
                client.patch(
                    f"/api/v1/viewings/{v_id}",
                    json={"notes": original_notes},
                    headers={"X-User-ID": "user-1"}
                )

    def test_lead_situation_enriched_history_tables(self):
        with TestClient(app) as client:
            # Fetch a lead situation
            res = client.get("/api/v1/leads/lead-2/situation", headers={"X-User-ID": "user-1"})
            self.assertEqual(res.status_code, 200)
            sit = res.json().get("data", {})

            # Check lead address elements
            self.assertIn("lead_id", sit)
            self.assertIn("lead_subject", sit)
            self.assertIn("current_stage", sit)
            self.assertIn("is_stalled", sit)

            # Check structured entity tables
            self.assertIn("tasks", sit)
            self.assertIn("activities", sit)
            self.assertIn("communications", sit)
            self.assertIn("viewings", sit)
            self.assertIn("offers", sit)
            self.assertIn("reservations", sit)
            self.assertIn("contracts", sit)
            self.assertIn("timeline", sit)

            # Check item fields in tasks
            if sit["tasks"]:
                t0 = sit["tasks"][0]
                self.assertIn("is_done", t0)
                self.assertIn("situation", t0)
                self.assertIn("date_time", t0)
                self.assertIn("title", t0)

            # Check item fields in viewings
            if sit["viewings"]:
                v0 = sit["viewings"][0]
                self.assertIn("is_done", v0)
                self.assertIn("situation", v0)
                self.assertIn("date_time", v0)
                self.assertIn("unit_number", v0)


if __name__ == "__main__":
    unittest.main()
