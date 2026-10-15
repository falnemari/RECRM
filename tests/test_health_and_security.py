import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestHealthAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_check_returns_200(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data["status"], "healthy")
        self.assertEqual(json_data["service"], "recrm-api")

    def test_security_headers_present(self):
        response = self.client.get("/health")
        headers = response.headers
        self.assertIn("x-request-id", headers)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(headers.get("referrer-policy"), "strict-origin-when-cross-origin")

    def test_root_redirects_to_docs(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/docs")

if __name__ == "__main__":
    unittest.main()

