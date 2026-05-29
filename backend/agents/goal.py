"""Goal Agent — assesses savings goal feasibility and suggests actions.

Flow:
  1. Code computes: required_monthly = target_amount / horizon_months
  2. Code fetches:  forecast_savings_mid from forecast agent
  3. Code computes: gap = required_monthly - forecast_savings_mid
  4. Code determines verdict: on_track | shortfall | surplus
  5. LLM (GPT-4o) generates ranked, actionable suggestions when there is a shortfall.
  6. What-if: user adjusts a category → code recalculates gap (no LLM call needed).

The LLM NEVER computes money totals — it only explains and suggests.
"""

import json
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from openai import AzureOpenAI

from backend.agents.analytics import compute_monthly_maps_in_range
from backend.agents.forecast import run_forecast
from backend.config import AzureOpenAIConfig
from backend.db.repository import TransactionRepository

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


class GoalAgent:
    def __init__(self, config: AzureOpenAIConfig, repo: TransactionRepository) -> None:
        self._config = config
        self._repo = repo
        self._client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )

    def assess(
        self,
        target_amount: Decimal,
        horizon_months: int,
        description: str = "",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """Assess goal feasibility.

        When ``start_date`` / ``end_date`` are set, the baseline forecast and
        category-spend averages are computed from the filtered window only.

        Returns:
          {
            required_monthly, forecast_monthly, gap,
            verdict,          # "on_track" | "shortfall" | "surplus"
            suggestions,      # list[{category, action, saving_amount, rationale}]
            goal_id,
          }
        """
        required_monthly = (target_amount / Decimal(horizon_months)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        # Forecast from the (possibly filtered) baseline.
        projections = run_forecast(
            self._repo, horizon=3, start_date=start_date, end_date=end_date,
        )
        if projections:
            forecast_monthly = projections[0]["savings_mid"]
        else:
            # Fall back to trailing average from monthly maps in the window.
            maps = self._maps_in_range(start_date, end_date)
            if maps:
                savings = [m["net_savings"] for m in maps[-3:]]
                forecast_monthly = sum(savings) / Decimal(len(savings))
            else:
                forecast_monthly = Decimal("0")

        forecast_monthly = forecast_monthly.quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP)
        gap = (required_monthly - forecast_monthly).quantize(TWO_PLACES,
                                                             rounding=ROUND_HALF_UP)

        if gap <= 0:
            verdict = "on_track" if gap == 0 else "surplus"
            suggestions: list[dict] = []
        else:
            verdict = "shortfall"
            suggestions = self._get_suggestions(
                gap, required_monthly, forecast_monthly, start_date, end_date,
            )

        goal_id = self._repo.save_goal(
            description=description,
            target_amount=target_amount,
            horizon_months=horizon_months,
            verdict=verdict,
            gap_per_month=gap,
            suggestions=suggestions,
        )

        return {
            "required_monthly": required_monthly,
            "forecast_monthly": forecast_monthly,
            "gap": gap,
            "verdict": verdict,
            "suggestions": suggestions,
            "goal_id": goal_id,
        }

    def _maps_in_range(
        self, start_date: Optional[date], end_date: Optional[date],
    ) -> list[dict]:
        if start_date or end_date:
            return compute_monthly_maps_in_range(self._repo, start_date, end_date)
        return self._repo.get_monthly_maps()

    def what_if(
        self,
        target_amount: Decimal,
        horizon_months: int,
        category_adjustments: dict[str, Decimal],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """Recalculate goal feasibility after hypothetical category spend changes.

        ``category_adjustments``: {category_name: new_monthly_spend}.
        No LLM call — pure arithmetic.
        """
        required_monthly = (target_amount / Decimal(horizon_months)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        projections = run_forecast(
            self._repo, horizon=1, start_date=start_date, end_date=end_date,
        )
        if projections:
            base_savings = projections[0]["savings_mid"]
            base_discretionary = projections[0]["discretionary_mid"]
        else:
            maps = self._maps_in_range(start_date, end_date)
            latest = maps[-1] if maps else {}
            base_savings = latest.get("net_savings", Decimal("0"))
            base_discretionary = latest.get("discretionary", Decimal("0"))

        # Compute current category averages (within the active range)
        monthly_cats = self._repo.get_monthly_category_breakdown(
            start_date, end_date)
        cat_monthly_avg: dict[str, Decimal] = {}
        cat_month_counts: dict[str, int] = {}
        for row in monthly_cats:
            cat = row["category"]
            cat_monthly_avg[cat] = cat_monthly_avg.get(
                cat, Decimal("0")) + Decimal(str(row["total"]))
            cat_month_counts[cat] = cat_month_counts.get(cat, 0) + 1
        for cat in cat_monthly_avg:
            if cat_month_counts[cat] > 0:
                cat_monthly_avg[cat] = cat_monthly_avg[cat] / \
                    Decimal(cat_month_counts[cat])

        # Apply adjustments
        savings_delta = Decimal("0")
        for cat, new_spend in category_adjustments.items():
            old_spend = cat_monthly_avg.get(cat, Decimal("0"))
            savings_delta += (old_spend - new_spend)

        adjusted_savings = (
            base_savings + savings_delta).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        gap = (required_monthly - adjusted_savings).quantize(TWO_PLACES,
                                                             rounding=ROUND_HALF_UP)

        if gap <= 0:
            verdict = "on_track" if gap == 0 else "surplus"
        else:
            verdict = "shortfall"

        return {
            "required_monthly": required_monthly,
            "adjusted_savings": adjusted_savings,
            "gap": gap,
            "verdict": verdict,
        }

    def _get_suggestions(
        self,
        gap: Decimal,
        required_monthly: Decimal,
        forecast_monthly: Decimal,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """Ask GPT-4o for ranked, concrete suggestions to close the savings gap."""
        # Build context from category breakdown in the active window.
        category_data = self._repo.get_categories_summary(start_date, end_date)
        monthly_maps = self._maps_in_range(start_date, end_date)
        n_months = len(monthly_maps) or 1

        # Average monthly spend per category
        cat_avg = []
        for c in category_data:
            monthly_avg = round(c["total"] / n_months, 2)
            cat_avg.append(
                {"category": c["category"], "monthly_avg_spend": monthly_avg})

        # Sort by spend descending (top 10)
        cat_avg.sort(key=lambda x: x["monthly_avg_spend"], reverse=True)
        top_cats = cat_avg[:10]

        system_prompt = (
            "You are a personal finance advisor for an Indian user. "
            "Given their monthly category spending and a savings gap, "
            "suggest 3-5 concrete, ranked actions to close the gap. "
            "Each suggestion must:\n"
            "- Name a specific category to cut\n"
            "- State a realistic reduction percentage\n"
            "- Calculate the rupee saving (reduction_pct × monthly_avg)\n"
            "- Give a one-line rationale\n\n"
            "CRITICAL RULES:\n"
            "- You MUST respond with valid JSON only — a list of objects.\n"
            "- Do NOT compute total savings or verify arithmetic. Just provide the suggestions.\n"
            "- Each object: {\"category\": str, \"action\": str, \"reduction_pct\": float, "
            "\"saving_amount\": float, \"rationale\": str}"
        )

        user_prompt = (
            f"Monthly savings gap to close: ₹{gap}\n"
            f"Current forecast monthly savings: ₹{forecast_monthly}\n"
            f"Required monthly savings: ₹{required_monthly}\n\n"
            f"Monthly category spending (INR):\n"
            + "\n".join(f"- {c['category']}: ₹{c['monthly_avg_spend']}" for c in top_cats)
        )

        try:
            response = self._client.chat.completions.create(
                model=self._config.deployment_reasoning,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "[]"
            # The model may return {"suggestions": [...]} or just [...]
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("suggestions", list(parsed.values())[0] if parsed else [])
            return []
        except Exception:
            logger.exception("Goal agent LLM call failed.")
            return []
