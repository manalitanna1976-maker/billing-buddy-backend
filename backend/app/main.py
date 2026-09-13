import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from app.config import get_settings
from app.routers import (
    auth,
    bank_accounts,
    business,
    customers,
    invoices,
    meta,
    products,
    purchases,
    suppliers,
    whatsapp,
)

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Billing Buddy CRM API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    # The default handler serialises exc.errors() verbatim, which can contain a
    # non-finite float `input` (e.g. a client sending 1e400) -> the JSON encoder
    # then raises and turns a clean 422 into a 500. Stringify every `input`.
    clean = []
    for err in exc.errors():
        e = dict(err)
        if "input" in e:
            try:
                import math

                if isinstance(e["input"], float) and not math.isfinite(e["input"]):
                    e["input"] = str(e["input"])
            except Exception:
                e["input"] = repr(e["input"])
        e.pop("ctx", None)
        e.pop("url", None)
        clean.append(e)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": clean})


@app.exception_handler(IntegrityError)
async def _integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("integrity error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "That change conflicts with existing data."},
    )


@app.exception_handler(DataError)
async def _data_error_handler(request: Request, exc: DataError):
    logger.warning("data error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "One or more values are out of the accepted range."},
    )


@app.exception_handler(SQLAlchemyError)
async def _db_error_handler(request: Request, exc: SQLAlchemyError):
    err_id = uuid.uuid4().hex[:12]
    logger.exception("db error %s on %s %s", err_id, request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Internal error (ref {err_id})."},
    )

app.include_router(auth.router)
app.include_router(business.router)
app.include_router(bank_accounts.router)
app.include_router(customers.router)
app.include_router(invoices.router)
app.include_router(meta.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(purchases.router)
app.include_router(whatsapp.router)

Path(get_settings().upload_dir).mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=get_settings().upload_dir), name="uploads")


@app.get("/health")
def health():
    return {"status": "ok"}
