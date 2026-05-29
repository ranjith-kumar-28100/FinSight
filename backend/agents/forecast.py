"""Forecast Agent — projects next 1–6 months assuming current patterns continue.

Method:
  Uses the last N months from monthly_maps as baseline:
  - income:        weighted average (most recent month ×3, others ×1)
  - fixed:         sum of active recurring series (deterministic)
  - discretionary: rolling average ± 1 standard deviation for confidence band
  - savings_mid:   income_avg - fixed - discretionary_avg
  - savings_low:   income_avg - fixed - (discretionary_avg + disc_std)
  - savings_high:  income_avg - fixed - (discretionary_avg - disc_std)

All arithmetic in Decimal. No LLM.
"""

import logging
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from backend.agents.analytics import compute_monthly_maps_in_range
from backend.db.repository import TransactionRepository

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
BASELINE_MONTHS = 3      # number of trailing months to use as baseline


def run_forecast(
    repo: TransactionRepository,
    horizon: int = 3,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict]:
    """Compute a forecast for the next `horizon` months.

    When ``start_date`` / ``end_date`` are supplied, the history baseline is
    recomputed from transactions in that range — so the forecast reflects only
    the filtered window.

    Returns a list of dicts:
      {month, income_mid, fixed, discretionary_low, discretionary_mid,
       discretionary_high, savings_low, savings_mid, savings_high}
    """
    if start_date or end_date:
        maps = compute_monthly_maps_in_range(repo, start_date, end_date)
    else:
        maps = repo.get_monthly_maps()
    if len(maps) < 1:
        logger.warning("Forecast: insufficient monthly map data.")
        return []

    # Use up to BASELINE_MONTHS most recent months
    baseline = maps[-BASELINE_MONTHS:]

    incomes = [m["income"] for m in baseline]
    fixeds = [m["fixed_obligations"] for m in baseline]
    discs = [m["discretionary"] for m in baseline]

    # Weighted average income: most recent × 3, rest × 1
    income_avg = _weighted_avg(incomes)

    # Fixed obligations: use max of recent months (conservative)
    fixed_avg = max(fixeds) if fixeds else Decimal("0")

    # Discretionary: average + std deviation
    disc_avg = _simple_avg(discs)
    disc_std = _std_dev(discs)

    # Next month after last observed month
    last_month = maps[-1]["month"]  # e.g. "2026-04"
    year, month = int(last_month[:4]), int(last_month[5:7])

    projections: list[dict] = []
    for _ in range(horizon):
        month += 1
        if month > 12:
            month = 1
            year += 1
        month_label = f"{year:04d}-{month:02d}"

        disc_low = max(Decimal("0"), disc_avg - disc_std)
        disc_high = disc_avg + disc_std

        sav_mid = (income_avg - fixed_avg -
                   disc_avg).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        sav_low = (income_avg - fixed_avg -
                   disc_high).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        sav_high = (income_avg - fixed_avg -
                    disc_low).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        projections.append({
            "month": month_label,
            "income_mid": income_avg.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            "fixed": fixed_avg.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            "discretionary_low": disc_low.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            "discretionary_mid": disc_avg.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            "discretionary_high": disc_high.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            "savings_low": sav_low,
            "savings_mid": sav_mid,
            "savings_high": sav_high,
        })

    logger.info("Forecast: projected %d months from baseline of %d.",
                horizon, len(baseline))
    return projections


def _weighted_avg(values: list[Decimal]) -> Decimal:
    """Most-recent-weighted average: last value ×3, rest ×1."""
    if not values:
        return Decimal("0")
    if len(values) == 1:
        return values[0]
    weights = [1] * len(values)
    weights[-1] = 3
    total_w = sum(weights)
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / Decimal(total_w)


def _simple_avg(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values) / Decimal(len(values))


def _std_dev(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    avg = _simple_avg(values)
    variance = sum((v - avg) ** 2 for v in values) / Decimal(len(values))
    # Integer square root via Newton's method for Decimal
    if variance <= 0:
        return Decimal("0")
    x = variance
    y = (x + 1) / 2
    while y < x:
        x = y
        y = (x + variance / x) / 2
    return x.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
