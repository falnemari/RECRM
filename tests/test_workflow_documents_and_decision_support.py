import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_workflow_documents_catalog_and_types():
    """Verify document types include all required Saudi workflow classifications."""
    with TestClient(app) as client:
        res = client.get("/api/v1/document-types")
        assert res.status_code == 200
        types = res.json().get("data", [])
        codes = {t["code"] for t in types}
        
        required_codes = [
            "DUE_DILIGENCE_REPORT",
            "COUNTER_OFFER_LETTER",
            "COMMERCIAL_OFFER",
            "BASELINE_FINANCIAL_SHEET",
            "TAQEEM_VALUATION",
            "TAX_ZAKAT_CLEARANCE",
            "TITLE_DEED",
            "SALE_CONTRACT",
            "LEASE",
            "INVOICE"
        ]
        for rc in required_codes:
            assert rc in codes, f"Document type {rc} missing from catalog"


def test_lead_114_has_all_decision_reference_documents():
    """Verify that lead-114 / opp-734 has all required decision reference documents in documents table."""
    with TestClient(app) as client:
        res = client.get("/api/v1/documents?lead_id=lead-114")
        assert res.status_code == 200
        docs = res.json().get("data", [])
        assert len(docs) >= 5, f"Expected at least 5 documents for lead-114, got {len(docs)}"
        
        doc_codes = {d["document_type_code"] for d in docs}
        assert "DUE_DILIGENCE_REPORT" in doc_codes
        assert "COUNTER_OFFER_LETTER" in doc_codes
        assert "COMMERCIAL_OFFER" in doc_codes
        assert "BASELINE_FINANCIAL_SHEET" in doc_codes
        assert "TAX_ZAKAT_CLEARANCE" in doc_codes


def test_html_render_for_all_document_types():
    """Ensure GET /api/v1/documents/{document_id}/html renders valid official printable layouts."""
    with TestClient(app) as client:
        # Fetch lead-114 documents
        res = client.get("/api/v1/documents?lead_id=lead-114")
        docs = res.json().get("data", [])
        
        for d in docs:
            doc_id = d["document_id"]
            html_res = client.get(f"/api/v1/documents/{doc_id}/html")
            assert html_res.status_code == 200
            assert "text/html" in html_res.headers.get("content-type", "")
            content = html_res.text
            assert "مكتب معاذ خضر النمري للخدمات العقارية" in content
            assert doc_id in content
            assert "print-toolbar" in content


def test_document_generate_api():
    """Verify POST /api/v1/documents/generate synthesizes and archives official documents on demand."""
    with TestClient(app) as client:
        payload = {
            "document_type_code": "SOIL_ENVIRONMENTAL_REPORT",
            "lead_id": "lead-114",
            "opportunity_id": "opportunity-734",
            "custom_payload": {
                "bearing_capacity": "300 kPa",
                "seismic_zone": "Zone 2B",
                "structural_notes": "SBC 303 compliant soil testing"
            }
        }
        res = client.post("/api/v1/documents/generate", json=payload)
        assert res.status_code == 201
        data = res.json().get("data", {})
        doc_id = data.get("document_id")
        assert doc_id is not None
        assert data.get("document_type_code") == "SOIL_ENVIRONMENTAL_REPORT"
        assert data.get("lead_id") == "lead-114"
        
        # Verify rendered HTML
        html_res = client.get(f"/api/v1/documents/{doc_id}/html")
        assert html_res.status_code == 200
        assert "تقرير جسات التربة والسلامة الإنشائية SBC" in html_res.text

