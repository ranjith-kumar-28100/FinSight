"""Goals — assess feasibility and what-if simulation."""

from fastapi import APIRouter, Depends

from backend.dependencies import get_app_config, get_repo
from backend.schemas import (
    GoalAssessRequest,
    GoalAssessResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from backend.agents.goal import GoalAgent
from backend.config import AppConfig
from backend.db.repository import TransactionRepository

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("/assess", response_model=GoalAssessResponse)
def assess(
    body: GoalAssessRequest,
    config: AppConfig = Depends(get_app_config),
    repo: TransactionRepository = Depends(get_repo),
) -> GoalAssessResponse:
    agent = GoalAgent(config.azure, repo)
    result = agent.assess(
        target_amount=body.target_amount,
        horizon_months=body.horizon_months,
        description=body.description,
        start_date=body.start,
        end_date=body.end,
    )
    return GoalAssessResponse(**result)


@router.post("/what-if", response_model=WhatIfResponse)
def what_if(
    body: WhatIfRequest,
    config: AppConfig = Depends(get_app_config),
    repo: TransactionRepository = Depends(get_repo),
) -> WhatIfResponse:
    agent = GoalAgent(config.azure, repo)
    result = agent.what_if(
        target_amount=body.target_amount,
        horizon_months=body.horizon_months,
        category_adjustments=body.adjustments,
        start_date=body.start,
        end_date=body.end,
    )
    return WhatIfResponse(**result)
