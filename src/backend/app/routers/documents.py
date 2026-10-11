from typing import Optional, List
from uuid import uuid4
from datetime import datetime, date, timezone
import hashlib
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope
from app.schemas.documents import (
    DocumentsSummaryOut,
    DocumentTypeOut,
    DocumentOut, DocumentCreateIn,
    DocumentAccessLogOut
)

router = APIRouter(tags=["Document Management"])

# ---------------------------------------------------------
# Summary / KPIs
# ---------------------------------------------------------
@router.get("/documents/summary", response_model=ResponseEnvelope[DocumentsSummaryOut])
async def get_documents_summary(conn: asyncpg.Connection = Depends(get_db)):
    total_docs = await conn.fetchval("SELECT count(*) FROM documents") or 0
    active_docs = await conn.fetchval("SELECT count(*) FROM documents WHERE status = 'ACTIVE'") or 0
    expiring_soon = await conn.fetchval(
        """
        SELECT count(*) FROM documents 
        WHERE status = 'ACTIVE' 
          AND expires_at IS NOT NULL 
          AND expires_at >= CURRENT_DATE 
          AND expires_at <= CURRENT_DATE + interval '30 days'
        """
    ) or 0
    expired = await conn.fetchval(
        "SELECT count(*) FROM documents WHERE expires_at IS NOT NULL AND expires_at < CURRENT_DATE"
    ) or 0
    total_access = await conn.fetchval("SELECT count(*) FROM document_access_log") or 0

    return ResponseEnvelope(data=DocumentsSummaryOut(
        total_documents=total_docs,
        active_documents=active_docs,
        expiring_soon_count=expiring_soon,
        expired_count=expired,
        total_access_events=total_access
    ))


# ---------------------------------------------------------
# Document Types Reference
# ---------------------------------------------------------
@router.get("/document-types", response_model=CollectionEnvelope[DocumentTypeOut])
async def list_document_types(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT document_type_id, code, name, expiry_required FROM document_types ORDER BY name ASC")
    data = [DocumentTypeOut(**dict(r)) for r in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )


# ---------------------------------------------------------
# Documents
# ---------------------------------------------------------
@router.get("/documents", response_model=CollectionEnvelope[DocumentOut])
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    document_type: Optional[str] = None,
    customer_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    is_expired: Optional[bool] = None,
    is_expiring_soon: Optional[bool] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if document_type:
        conditions.append(f"dt.code = ${p_idx}")
        params.append(document_type.upper())
        p_idx += 1

    if customer_id:
        conditions.append(f"d.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if unit_id:
        conditions.append(f"d.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if contract_id:
        conditions.append(f"d.contract_id = ${p_idx}")
        params.append(contract_id)
        p_idx += 1

    if status_filter:
        conditions.append(f"d.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if is_expired:
        conditions.append("d.expires_at IS NOT NULL AND d.expires_at < CURRENT_DATE")

    if is_expiring_soon:
        conditions.append("d.status = 'ACTIVE' AND d.expires_at IS NOT NULL AND d.expires_at >= CURRENT_DATE AND d.expires_at <= CURRENT_DATE + interval '30 days'")

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(d.file_name ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR u.unit_number ILIKE ${p_idx} OR con.contract_number ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM documents d
        LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
        LEFT JOIN customers c ON d.customer_id = c.customer_id
        LEFT JOIN units u ON d.unit_id = u.unit_id
        LEFT JOIN contracts con ON d.contract_id = con.contract_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            d.document_id,
            d.organization_id,
            d.document_type_id,
            dt.code AS document_type_code,
            dt.name AS document_type_name,
            d.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            d.unit_id,
            u.unit_number,
            d.contract_id,
            con.contract_number,
            d.file_name,
            d.storage_uri,
            d.file_hash,
            d.version_no,
            d.issued_at,
            d.expires_at,
            d.status,
            d.uploaded_by_user_id,
            usr.full_name AS uploaded_by_name,
            d.created_at,
            CASE WHEN d.expires_at IS NOT NULL AND d.expires_at < CURRENT_DATE THEN true ELSE false END AS is_expired,
            CASE WHEN d.status = 'ACTIVE' AND d.expires_at IS NOT NULL AND d.expires_at >= CURRENT_DATE AND d.expires_at <= CURRENT_DATE + interval '30 days' THEN true ELSE false END AS is_expiring_soon
        FROM documents d
        LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
        LEFT JOIN customers c ON d.customer_id = c.customer_id
        LEFT JOIN units u ON d.unit_id = u.unit_id
        LEFT JOIN contracts con ON d.contract_id = con.contract_id
        LEFT JOIN users usr ON d.uploaded_by_user_id = usr.user_id
        WHERE {where_clause}
        ORDER BY d.created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [DocumentOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/documents", response_model=ResponseEnvelope[DocumentOut], status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreateIn,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db)
):
    org = await conn.fetchrow("SELECT organization_id FROM organizations WHERE status = 'ACTIVE' LIMIT 1")
    if not org:
        org = await conn.fetchrow("SELECT organization_id FROM organizations LIMIT 1")
    org_id = org["organization_id"]

    doc_type_id = payload.document_type_id
    code = (payload.document_type_code or "TITLE_DEED").upper()
    doc_type_name = "Document"

    if not doc_type_id and code:
        dt = await conn.fetchrow("SELECT document_type_id, name FROM document_types WHERE code = $1", code)
        if dt:
            doc_type_id = dt["document_type_id"]
            doc_type_name = dt["name"]

    doc_id = await get_next_id(conn, "documents", "document")
    now = datetime.now(timezone.utc)
    storage_uri = payload.storage_uri or f"s3://recrm-documents/{org_id}/{doc_id}/{payload.file_name}"
    
    # Generate unique sha256 hash for deduplication and integrity
    file_hash = hashlib.sha256(f"{doc_id}-{payload.file_name}-{now.isoformat()}".encode()).hexdigest()

    user_id = payload.uploaded_by_user_id
    user_name = None
    if not user_id:
        default_user = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE status = 'ACTIVE' LIMIT 1")
        if default_user:
            user_id = default_user["user_id"]
            user_name = default_user["full_name"]
    else:
        usr = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", user_id)
        if usr:
            user_name = usr["full_name"]

    cust_name = None
    if payload.customer_id:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    unit_number = None
    if payload.unit_id:
        u = await conn.fetchrow("SELECT unit_number FROM units WHERE unit_id = $1", payload.unit_id)
        if u:
            unit_number = u["unit_number"]

    contract_number = None
    if payload.contract_id:
        con = await conn.fetchrow("SELECT contract_number FROM contracts WHERE contract_id = $1", payload.contract_id)
        if con:
            contract_number = con["contract_number"]

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO documents (
                document_id, organization_id, document_type_id, customer_id, unit_id, contract_id,
                file_name, storage_uri, file_hash, version_no, issued_at, expires_at,
                status, uploaded_by_user_id, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1, $10, $11, $12, $13, $14)
            """,
            doc_id, org_id, doc_type_id, payload.customer_id, payload.unit_id, payload.contract_id,
            payload.file_name, storage_uri, file_hash, payload.issued_at, payload.expires_at,
            payload.status or "ACTIVE", user_id, now
        )

        # Log creation/upload action
        client_ip = request.client.host if request.client else "127.0.0.1"
        await conn.execute(
            """
            INSERT INTO document_access_log (
                document_id, user_id, action, accessed_at, ip_address
            ) VALUES ($1, $2, 'UPLOAD', $3, $4)
            """,
            doc_id, user_id, now, client_ip
        )

    is_exp = bool(payload.expires_at and payload.expires_at < date.today())

    out = DocumentOut(
        document_id=doc_id,
        organization_id=org_id,
        document_type_id=doc_type_id,
        document_type_code=code,
        document_type_name=doc_type_name,
        customer_id=payload.customer_id,
        customer_name=cust_name,
        unit_id=payload.unit_id,
        unit_number=unit_number,
        contract_id=payload.contract_id,
        contract_number=contract_number,
        file_name=payload.file_name,
        storage_uri=storage_uri,
        file_hash=file_hash,
        version_no=1,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        status=payload.status or "ACTIVE",
        uploaded_by_user_id=user_id,
        uploaded_by_name=user_name,
        created_at=now,
        is_expired=is_exp,
        is_expiring_soon=False
    )
    return ResponseEnvelope(data=out)

@router.get("/documents/{document_id}", response_model=ResponseEnvelope[DocumentOut])
async def get_document(
    document_id: str,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db)
):
    row = await conn.fetchrow(
        """
        SELECT 
            d.document_id,
            d.organization_id,
            d.document_type_id,
            dt.code AS document_type_code,
            dt.name AS document_type_name,
            d.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            d.unit_id,
            u.unit_number,
            d.contract_id,
            con.contract_number,
            d.file_name,
            d.storage_uri,
            d.file_hash,
            d.version_no,
            d.issued_at,
            d.expires_at,
            d.status,
            d.uploaded_by_user_id,
            usr.full_name AS uploaded_by_name,
            d.created_at,
            CASE WHEN d.expires_at IS NOT NULL AND d.expires_at < CURRENT_DATE THEN true ELSE false END AS is_expired,
            CASE WHEN d.status = 'ACTIVE' AND d.expires_at IS NOT NULL AND d.expires_at >= CURRENT_DATE AND d.expires_at <= CURRENT_DATE + interval '30 days' THEN true ELSE false END AS is_expiring_soon
        FROM documents d
        LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
        LEFT JOIN customers c ON d.customer_id = c.customer_id
        LEFT JOIN units u ON d.unit_id = u.unit_id
        LEFT JOIN contracts con ON d.contract_id = con.contract_id
        LEFT JOIN users usr ON d.uploaded_by_user_id = usr.user_id
        WHERE d.document_id = $1
        """,
        document_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    # Record access log
    default_user = await conn.fetchrow("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1")
    user_id = default_user["user_id"] if default_user else row["uploaded_by_user_id"]
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    await conn.execute(
        """
        INSERT INTO document_access_log (
            document_id, user_id, action, accessed_at, ip_address
        ) VALUES ($1, $2, 'VIEW', NOW(), $3)
        """,
        document_id, user_id, client_ip
    )

    return ResponseEnvelope(data=DocumentOut(**dict(row)))

@router.post("/documents/{document_id}/access-url", response_model=ResponseEnvelope[dict])
async def generate_access_url(
    document_id: str,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db)
):
    doc = await conn.fetchrow("SELECT document_id, file_name, storage_uri FROM documents WHERE document_id = $1", document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    default_user = await conn.fetchrow("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1")
    user_id = default_user["user_id"] if default_user else "user-1"
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Log download action
    await conn.execute(
        """
        INSERT INTO document_access_log (
            document_id, user_id, action, accessed_at, ip_address
        ) VALUES ($1, $2, 'DOWNLOAD', NOW(), $3)
        """,
        document_id, user_id, client_ip
    )

    signed_token = uuid4().hex
    access_url = f"https://storage.recrm.sa/signed-access/{document_id}/{doc['file_name']}?token={signed_token}&expires_in=3600"

    return ResponseEnvelope(data={
        "document_id": str(document_id),
        "file_name": doc["file_name"],
        "access_url": access_url,
        "expires_in_seconds": 3600
    })

@router.get("/documents/{document_id}/access-log", response_model=CollectionEnvelope[DocumentAccessLogOut])
async def get_document_access_log(
    document_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    total = await conn.fetchval("SELECT count(*) FROM document_access_log WHERE document_id = $1", document_id)

    rows = await conn.fetch(
        """
        SELECT 
            dal.document_access_id,
            dal.document_id,
            dal.user_id,
            u.full_name AS user_name,
            dal.action,
            dal.accessed_at,
            dal.ip_address
        FROM document_access_log dal
        LEFT JOIN users u ON dal.user_id = u.user_id
        WHERE dal.document_id = $1
        ORDER BY dal.accessed_at DESC
        LIMIT $2 OFFSET $3
        """,
        document_id, page_size, offset
    )
    data = [DocumentAccessLogOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/documents/{document_id}/archive", response_model=ResponseEnvelope[dict])
async def archive_document(
    document_id: str,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db)
):
    doc = await conn.fetchrow("SELECT document_id, status FROM documents WHERE document_id = $1", document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    default_user = await conn.fetchrow("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1")
    user_id = default_user["user_id"] if default_user else "user-1"
    client_ip = request.client.host if request.client else "127.0.0.1"

    async with conn.transaction():
        await conn.execute("UPDATE documents SET status = 'ARCHIVED' WHERE document_id = $1", document_id)
        await conn.execute(
            """
            INSERT INTO document_access_log (
                document_id, user_id, action, accessed_at, ip_address
            ) VALUES ($1, $2, 'ARCHIVE', NOW(), $3)
            """,
            document_id, user_id, client_ip
        )

    return ResponseEnvelope(data={"document_id": str(document_id), "status": "ARCHIVED"})

