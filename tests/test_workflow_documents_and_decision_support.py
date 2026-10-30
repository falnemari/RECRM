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
        res = client.get("/api/v1/documents?lead_id=lead-114&page_size=100")
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
        res = client.get("/api/v1/documents?lead_id=lead-114&page_size=100")
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

        # Clean up generated test document immediately to prevent duplicate bloat
        del_res = client.delete(f"/api/v1/documents/{doc_id}")
        assert del_res.status_code == 200


def test_due_diligence_report_dynamic_fields_and_fidelity():
    """Verify that DUE_DILIGENCE_REPORT renders actual data dynamically without hardcoded names or mock defects."""
    with TestClient(app) as client:
        # Check document-1579 (or any active due diligence report)
        res = client.get("/api/v1/documents/document-1579/html")
        assert res.status_code == 200
        html = res.text
        
        # Verify no hardcoded fake names or fake repair amounts
        assert "عبد الرحمن الغامدي" not in html
        assert "85,000.00" not in html
        assert "68,000.00" not in html
        assert "45,000.00" not in html
        assert "30,000.00" not in html
        
        # Verify actual investor, inspector, and financial metrics are present
        assert "Demo Agent 23" in html
        assert "Maan Othman" in html
        assert "7,500.00" in html
        assert "126,000.00" in html
        assert "8.40%" in html
        assert "95.0%" in html
        assert "ملتزمين" in html
        assert "دراسة الجدوى والتحليل المالي الاستثماري" in html


def test_documents_pagination_and_large_page_size():
    """Verify that GET /api/v1/documents supports pagination and large page_size."""
    with TestClient(app) as client:
        # Test large page size (500)
        res = client.get("/api/v1/documents?page_size=500")
        assert res.status_code == 200
        data = res.json()
        docs = data.get("data", [])
        meta = data.get("meta", {})
        
        total = meta.get("total", 0)
        assert total >= 20, f"Expected total >= 20, got {total}"
        assert len(docs) == total, f"Expected {total} documents in page 1 with page_size=500, got {len(docs)}"
        assert meta.get("page_size") == 500
        assert meta.get("page") == 1

        # Test small page size (10)
        res_p10 = client.get("/api/v1/documents?page=1&page_size=10")
        assert res_p10.status_code == 200
        data_p10 = res_p10.json()
        assert len(data_p10.get("data", [])) == 10
        assert data_p10.get("meta", {}).get("total") == total


def test_documents_search_and_arabic_normalization():
    """Verify server-side search across all documents with Arabic normalization and multi-field matching."""
    with TestClient(app) as client:
        # Search for فحص
        res = client.get("/api/v1/documents?page_size=500&search=فحص")
        assert res.status_code == 200
        docs = res.json().get("data", [])
        assert len(docs) >= 2, f"Expected at least 2 docs matching 'فحص', got {len(docs)}"

        # Search with hamza variation: إشعار vs اشعار
        res_esh = client.get("/api/v1/documents?page_size=100&search=إشعار")
        res_ash = client.get("/api/v1/documents?page_size=100&search=اشعار")
        assert res_esh.status_code == 200
        assert res_ash.status_code == 200
        # Both must return the same results thanks to Arabic normalization
        assert len(res_esh.json().get("data", [])) == len(res_ash.json().get("data", []))
        assert len(res_esh.json().get("data", [])) >= 1

        # Search for unit number
        res_unit = client.get("/api/v1/documents?page_size=100&search=104")
        assert res_unit.status_code == 200
        assert len(res_unit.json().get("data", [])) >= 1


def test_documents_category_filtering():
    """Verify server-side category tabs filter documents correctly."""
    with TestClient(app) as client:
        # Inspection category
        res_insp = client.get("/api/v1/documents?page_size=500&category=INSPECTION")
        assert res_insp.status_code == 200
        insp_docs = res_insp.json().get("data", [])
        assert len(insp_docs) >= 5
        for d in insp_docs:
            code = d.get("document_type_code", "")
            assert any(k in code for k in ["DILIGENCE", "TAQEEM", "BASELINE", "SOIL", "DEFECT", "COMPARATIVE"])

        # Offers category
        res_off = client.get("/api/v1/documents?page_size=500&category=OFFERS")
        assert res_off.status_code == 200
        off_docs = res_off.json().get("data", [])
        assert len(off_docs) >= 5
        for d in off_docs:
            code = d.get("document_type_code", "")
            assert any(k in code for k in ["OFFER", "COUNTER", "RESERVATION"])



