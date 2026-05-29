"""Upload + pipeline trigger."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.dependencies import (
    get_app_config,
    invalidate_chat_cache,
)
from backend.schemas import PipelineResponse
from backend.agents.ingestion import MAX_FILE_SIZE_BYTES, save_upload
from backend.agents.orchestrator import run_pipeline
from backend.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])


def _save(upload: UploadFile, upload_dir: Path) -> Path:
    data = upload.file.read()
    if not data:
        raise HTTPException(400, f"{upload.filename}: empty file")
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"{upload.filename}: exceeds size limit")
    return save_upload(data, upload.filename or "upload", upload_dir)


@router.post("", response_model=PipelineResponse)
async def upload_and_run(
    hdfc: Optional[UploadFile] = File(default=None),
    gpay: Optional[UploadFile] = File(default=None),
    paytm: Optional[UploadFile] = File(default=None),
    config: AppConfig = Depends(get_app_config),
) -> PipelineResponse:
    """Accept up to three statement files and run the FinSight pipeline."""
    saved: dict[str, Optional[Path]] = {"hdfc": None, "gpay": None, "paytm": None}
    if hdfc:
        saved["hdfc"] = _save(hdfc, config.upload_dir)
    if gpay:
        saved["gpay"] = _save(gpay, config.upload_dir)
    if paytm:
        saved["paytm"] = _save(paytm, config.upload_dir)

    if not any(saved.values()):
        raise HTTPException(400, "Upload at least one statement file.")

    try:
        state = run_pipeline(
            config=config.azure,
            db_path=config.db_path,
            hdfc_path=saved["hdfc"],
            gpay_path=saved["gpay"],
            paytm_path=saved["paytm"],
        )
    except Exception as e:
        logger.exception("Pipeline failed.")
        raise HTTPException(500, f"Pipeline failed: {e}") from e

    invalidate_chat_cache()
    return PipelineResponse(
        status=state.get("status", "complete"),
        errors=state.get("errors", []),
        ingestion=state.get("ingestion_summary", {}),
        reconciliation=state.get("reconciliation_summary", {}),
        categorisation=state.get("categorisation_summary", {}),
        recurring=state.get("recurring_summary", {}),
        analytics=state.get("analytics_summary", {}),
        anomaly=state.get("anomaly_summary", {}),
    )


@router.delete("/data")
def clear_all(
    config: AppConfig = Depends(get_app_config),
) -> dict:
    """Wipe all transactions and derived tables (sidebar Danger Zone)."""
    from backend.db.repository import TransactionRepository
    repo = TransactionRepository(config.db_path)
    deleted = repo.clear_all()
    invalidate_chat_cache()
    return {"deleted": deleted}
