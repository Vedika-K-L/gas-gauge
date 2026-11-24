"""Gas calculations and consumption analytics (pure functions, no Streamlit)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

NOISE_KG = 0.005          # ignore weight changes smaller than this between bins
BIN_FREQ = "15min"        # medians over this window suppress load-cell noise
MIN_SPAN_FOR_AVERAGE = timedelta(hours=6)


# --------------------------------------------------------------------------
# Calibration and gas formulas
# --------------------------------------------------------------------------
def calibrate(raw, settings, tag: str):
    """Dashboard-side calibration. Applies to physical hardware ('arduino') readings only.

    Works on scalars and pandas Series. The defaults (factor 1.0, offset 0.0) leave
    values unchanged; no calibration values are invented here.
    """
    if tag == "arduino":
        return raw * settings.calibration_factor + settings.tare_offset_kg
    return raw


def calibrate_scalar(raw: Optional[float], settings, tag: str) -> Optional[float]:
    if raw is None:
        return None
    return float(calibrate(raw, settings, tag))


def range_tolerance(settings) -> float:
    return max(0.2, 0.02 * settings.cylinder_capacity_kg)


def gas_status(pct: Optional[float], settings) -> tuple[str, str]:
    """(label, tone). Defaults mirror the sketch: >60 normal, >25 medium, else low."""
    if pct is None:
        return "NO DATA", "none"
    if pct > settings.medium_pct:
        return "NORMAL", "ok"
    if pct > settings.low_pct:
        return "MEDIUM", "mid"
    if pct > settings.critical_pct:
        return "LOW", "warn"
    return "CRITICAL", "crit"


@dataclass
class Gas:
    weight: Optional[float]
    remaining_kg: Optional[float]
    level_pct: Optional[float]
    out_of_range: bool
    status: str
    tone: str


def gas_from_weight(weight: Optional[float], settings) -> Gas:
    """Remaining = weight - empty; percent = remaining / capacity * 100.

    Remaining is clamped to [0, capacity] and percent to [0, 100]; readings outside
    the expected range (beyond a tolerance) are flagged so the UI can warn.
    """
    if weight is None or not math.isfinite(weight):
        return Gas(None, None, None, False, "NO DATA", "none")
    capacity = settings.cylinder_capacity_kg
    raw_remaining = weight - settings.empty_cylinder_weight_kg
    remaining = min(max(raw_remaining, 0.0), capacity)
    pct = min(max(remaining / capacity * 100.0, 0.0), 100.0)
    tol = range_tolerance(settings)
    out_of_range = raw_remaining < -tol or raw_remaining > capacity + tol
    status, tone = gas_status(pct, settings)
    return Gas(float(weight), remaining, pct, out_of_range, status, tone)


def enrich(df: pd.DataFrame, settings, tag: str) -> pd.DataFrame:
    """Add calibrated weight, remaining_kg and level_pct columns to a history frame."""
    out = df.copy()
    if out.empty:
        for col in ("weight", "remaining_kg", "level_pct"):
            out[col] = pd.Series(dtype="float64")
        return out
    out["weight"] = calibrate(out["weight_raw"], settings, tag)
    remaining = (out["weight"] - settings.empty_cylinder_weight_kg).clip(
        lower=0, upper=settings.cylinder_capacity_kg
    )
    out["remaining_kg"] = remaining
    out["level_pct"] = (remaining / settings.cylinder_capacity_kg * 100.0).clip(0, 100)
    return out


def downsample(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Median per time bin (gaps stay NaN so charts show them as breaks)."""
    if df.empty:
        return df
    cols = [c for c in ("weight", "remaining_kg", "level_pct") if c in df.columns]
    return df.set_index("ts")[cols].resample(freq).median().reset_index()


# --------------------------------------------------------------------------
# Consumption
# --------------------------------------------------------------------------
def consumption_series(df: pd.DataFrame, settings) -> pd.Series:
    """kg consumed per 15-minute bin.

    Only decreases between adjacent bins count. Increases (refills) are ignored, and
    drops larger than the abnormal-change threshold are treated as events (cylinder
    removed, spike) rather than consumption.
    """
    if df.empty or "weight" not in df.columns:
        return pd.Series(dtype="float64")
    weights = df.dropna(subset=["weight"]).set_index("ts")["weight"]
    if weights.empty:
        return pd.Series(dtype="float64")
    binned = weights.resample(BIN_FREQ).median()
    delta = binned.diff()
    valid = (delta < -NOISE_KG) & (delta > -settings.abnormal_delta_kg)
    return (-delta).where(valid, 0.0)


def consumed_since(df: pd.DataFrame, settings, start: datetime) -> Optional[float]:
    series = consumption_series(df, settings)
    if series.empty:
        return None
    return float(series[series.index >= pd.Timestamp(start)].sum())


def consumption_buckets(df: pd.DataFrame, settings, freq: str, start: datetime, end: datetime) -> pd.Series:
    """Consumption summed per bucket, with empty buckets as 0 across the whole window."""
    index = pd.date_range(pd.Timestamp(start).floor(freq), pd.Timestamp(end).floor(freq), freq=freq)
    series = consumption_series(df, settings)
    if series.empty:
        return pd.Series(0.0, index=index)
    return series.resample(freq).sum().reindex(index, fill_value=0.0)


def average_daily(df: pd.DataFrame, settings) -> Optional[float]:
    """Average kg/day over the supplied window; None until at least 6 hours of data exist."""
    if df.empty:
        return None
    span = df["ts"].max() - df["ts"].min()
    if span < MIN_SPAN_FOR_AVERAGE:
        return None
    total = float(consumption_series(df, settings).sum())
    return total / (span.total_seconds() / 86400.0)


def estimated_days(remaining_kg: Optional[float], avg_daily_kg: Optional[float]) -> Optional[float]:
    """Estimated days remaining = remaining LPG / average daily consumption."""
    if remaining_kg is None or avg_daily_kg is None or avg_daily_kg <= 1e-6:
        return None
    return remaining_kg / avg_daily_kg


@dataclass
class Metrics:
    gas: Gas
    consumed_today: Optional[float]
    avg_daily: Optional[float]
    days_remaining: Optional[float]
    refill_date: Optional[date]
    last_refill: Optional[date]


def build_metrics(gas: Gas, df7: pd.DataFrame, settings, now: datetime, last_refill: Optional[date]) -> Metrics:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    avg = average_daily(df7, settings)
    days = estimated_days(gas.remaining_kg, avg)
    refill = (now + timedelta(days=days)).date() if days is not None and days < 3650 else None
    return Metrics(gas, consumed_since(df7, settings, midnight), avg, days, refill, last_refill)
