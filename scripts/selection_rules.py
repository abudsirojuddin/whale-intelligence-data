"""Common and auditable research quality gates for V4.4.
A qualifying wallet is *not* a predictive trading signal.
"""
from datetime import datetime, timezone
import math

MAX_AGE_HOURS = 48
MIN_QUALITY_SCORE = 65
MIN_PROFIT_FACTOR = 1.5
MAX_REALIZED_DRAWDOWN_PROXY = 0.10
MIN_CLOSING_DAYS = 10
MIN_CLOSING_ORDERS = 20

def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (ValueError, TypeError, OverflowError):
        return 0.0

def time_of(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0

def is_qualified(row, now=None):
    if not isinstance(row, dict) or row.get("quality") != "EVALUATED":
        return False
    now = now or datetime.now(timezone.utc).timestamp()
    age = now - time_of(row.get("checkedAt"))
    return (
        0 <= age < MAX_AGE_HOURS * 3600 and
        number(row.get("score")) >= MIN_QUALITY_SCORE and
        number(row.get("netRealizedExFunding30")) > 0 and
        number(row.get("profitFactorCloseOrders30")) >= MIN_PROFIT_FACTOR and
        0 <= number(row.get("realizedDrawdownProxyToEquity")) <= MAX_REALIZED_DRAWDOWN_PROXY and
        number(row.get("closingDays30")) >= MIN_CLOSING_DAYS and
        number(row.get("closingOrders30")) >= MIN_CLOSING_ORDERS and
        row.get("historyTruncated") is False
    )

def activity_profile(row):
    """Intensity of observed closing orders, NOT position holding duration."""
    if not isinstance(row, dict) or row.get("quality") != "EVALUATED":
        return "UNKNOWN"
    days = number(row.get("closingDays30"))
    orders = number(row.get("closingOrders30"))
    if days < 7 or orders < 20:
        return "UNKNOWN"
    rate = orders / days
    if rate >= 8:
        return "HIGH_FREQUENCY_ACTIVITY"
    if rate <= 2:
        return "LOW_FREQUENCY_ACTIVITY"
    return "MODERATE_FREQUENCY_ACTIVITY"

def review_tier(row, now=None):
    if is_qualified(row, now):
        return "RESEARCH_PRIORITY"
    if not isinstance(row, dict):
        return "NO_DATA"
    if row.get("quality") == "EVALUATED":
        return "EVALUATED_NOT_QUALIFIED"
    return "INSUFFICIENT_EVIDENCE"
