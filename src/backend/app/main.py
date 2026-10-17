import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

import asyncio
import logging
from app.config import settings
from app.database import init_db_pool, close_db_pool, pool
from app.schemas.common import ErrorEnvelope, ErrorDetail
from app.routers import auth, reference, leads, customers, properties, sales, management, reports, finance, communications, documents, marketing, listings, admin

logger = logging.getLogger("recrm.scheduler")

async def reservation_expiry_worker():
    """
    Background worker that runs periodically to check for expiring or expired reservations.
    - Releases units and cancels reservations when 48h SLA passes without earnest deposit.
    - Alerts managers with TASK_RESERVATION_EXPIRY_REVIEW when approaching expiration.
    """
    while True:
        try:
            await asyncio.sleep(60)
            if pool:
                async with pool.acquire() as conn:
                    from app.services.workflow_engine import WorkflowEngine
                    await WorkflowEngine.process_expired_reservations(conn)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Reservation expiry worker error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB Pool and Expiry Worker
    await init_db_pool()
    worker_task = asyncio.create_task(reservation_expiry_worker())
    yield
    # Shutdown: Cancel worker & Close DB Pool
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await close_db_pool()


app = FastAPI(
    title="Real Estate CRM API",
    version="1.0.0",
    description="Production-ready REST API for Saudi Real Estate Brokerage and Property Management platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation / Request ID and Security Headers Middleware
@app.middleware("http")
async def add_correlation_id_and_security_headers(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Standardized Validation Error Handler matching API.md
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    field_errors = {}
    for err in exc.errors():
        loc = ".".join(str(l) for l in err["loc"] if l != "body")
        msg = err["msg"]
        field_errors.setdefault(loc, []).append(msg)

    error_body = ErrorEnvelope(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="One or more fields are invalid.",
            request_id=req_id,
            fields=field_errors
        )
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_body.model_dump())

# Root redirection
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/docs")

# Health Check
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "recrm-api", "version": "1.0.0", "database": settings.DB_NAME}

# Register v1 Routers
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(reference.router, prefix=settings.API_PREFIX)
app.include_router(leads.router, prefix=settings.API_PREFIX)
app.include_router(customers.router, prefix=settings.API_PREFIX)
app.include_router(properties.router, prefix=settings.API_PREFIX)
app.include_router(sales.router, prefix=settings.API_PREFIX)
app.include_router(management.router, prefix=settings.API_PREFIX)
app.include_router(reports.router, prefix=settings.API_PREFIX)
app.include_router(finance.router, prefix=settings.API_PREFIX)
app.include_router(communications.router, prefix=settings.API_PREFIX)
app.include_router(documents.router, prefix=settings.API_PREFIX)
app.include_router(marketing.router, prefix=settings.API_PREFIX)
app.include_router(listings.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)

# Mount Static UI prototype
UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

