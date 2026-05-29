"""FinSight FastAPI backend.

Run with:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.dependencies import get_app_config
from backend.routers import (
    analytics,
    anomalies,
    chat,
    forecast,
    goals,
    health,
    recurring,
    transactions,
    upload,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise config + DB up-front so ingest errors don't first surface on a request.
    cfg = get_app_config()
    logger.info("FinSight backend ready. DB=%s", cfg.db_path)
    yield


app = FastAPI(
    title="FinSight API",
    version="0.3.0",
    description=(
        "Personal finance intelligence — HDFC bank statement is the source of truth, "
        "Paytm/GPay wallets enrich UPI merchants. Hybrid RAG over transactions for chat."
    ),
    lifespan=lifespan,
)

# CORS — accept the Vite dev server out of the box; tighten in production via env.
_allowed = os.getenv(
    "FINSIGHT_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    return {
        "name": "FinSight API",
        "version": app.version,
        "docs": "/docs",
    }


# Mount routers under /api so the React app proxies cleanly.
API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(upload.router, prefix=API_PREFIX)
app.include_router(transactions.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
app.include_router(recurring.router, prefix=API_PREFIX)
app.include_router(forecast.router, prefix=API_PREFIX)
app.include_router(goals.router, prefix=API_PREFIX)
app.include_router(anomalies.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
