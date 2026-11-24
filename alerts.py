"""Alert rules and the connection summary shared by header, cards and notifications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

ABNORMAL_WINDOW_MIN = 10


@dataclass(frozen=True)
class Alert:
    code: str
    level: str   # "critical" | "warning" | "info"
    title: str
    message: str


_LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Connection:
    code: str     # ok | demo | imported | error | connecting | fault | no_data | waiting | ready
    label: str
    tone: str     # ok | demo | warn | crit
    detail: str


def connection_summary(snap: dict, settings) -> Connection:
    """Describe the connection state in one place so every widget agrees."""
    mode = snap["mode"]
    state = snap["state"]
    latest = snap["latest"]
    age = snap["age_s"]

    if state == "error":
        return Connection("error", "ERROR", "crit", snap["message"])
    if state != "connected":
        return Connection("connecting", "CONNECTING", "warn", snap["message"] or "Connecting...")
    if latest is not None and (latest.sensor_status != "connected" or latest.weight is None):
        return Connection("fault", "SENSOR FAULT", "crit", "The sensor reported an invalid weight.")

    if snap["streaming"]:
        reference = age if age is not None else (snap["connected_for_s"] or 0.0)
        if reference > settings.stale_seconds:
            return Connection("no_data", "NO DATA", "crit", f"No readings for {reference:.0f} s.")
        if age is None:
            return Connection("waiting", "WAITING", "warn", "Connected. Waiting for the first reading.")
    elif latest is None:
        return Connection("ready", "READY", "warn", "Ready. Paste serial text in Settings > Data source.")

    if mode == "demo":
        return Connection("demo", "SIMULATED", "demo", "Demo generator. Not a real sensor.")
    if not snap["streaming"]:
        return Connection("imported", "IMPORTED", "ok", "Readings imported from pasted text.")
    return Connection("ok", "LIVE", "ok", snap["source_label"])


def _recent_jump(df: pd.DataFrame, now: datetime, abnormal_kg: float) -> Optional[tuple[datetime, float]]:
    if df.empty or "weight" not in df.columns:
        return None
    window = df.dropna(subset=["weight"])
    window = window[window["ts"] >= now - timedelta(minutes=ABNORMAL_WINDOW_MIN)]
    if len(window) < 2:
        return None
    delta = window["weight"].diff()
    events = delta[delta.abs() >= abnormal_kg]
    if events.empty:
        return None
    position = delta.index.get_loc(events.index[-1])
    return window["ts"].iloc[position].to_pydatetime(), float(events.iloc[-1])


def evaluate(snap: dict, conn: Connection, gas, recent: pd.DataFrame, settings, now: Optional[datetime] = None) -> list[Alert]:
    """Return the currently active alerts, most severe first."""
    now = now or datetime.now()
    out: list[Alert] = []

    if conn.code == "error":
        out.append(Alert("connection_error", "critical", "Connection error", conn.detail))
    elif conn.code in ("fault", "no_data"):
        title = "Sensor disconnected" if conn.code == "no_data" else "Sensor fault"
        out.append(Alert("sensor_disconnected", "critical", title,
                         conn.detail + " Check the load cell, HX711 wiring and the serial link."))
    elif conn.code in ("connecting", "waiting", "ready"):
        out.append(Alert("connecting", "info", conn.label.title(), conn.detail))

    if gas.level_pct is not None and conn.code not in ("fault",):
        if gas.level_pct <= settings.critical_pct:
            out.append(Alert("gas_critical", "critical", "Critical gas level",
                             f"Only {gas.level_pct:.0f}% left ({gas.remaining_kg:.2f} kg). Replace or refill the cylinder now."))
        elif gas.level_pct <= settings.low_pct:
            out.append(Alert("gas_low", "warning", "Low gas level",
                             f"{gas.level_pct:.0f}% left ({gas.remaining_kg:.2f} kg). Plan a refill soon."))
        if gas.out_of_range:
            out.append(Alert("out_of_range", "warning", "Weight outside expected range",
                             f"{gas.weight:.2f} kg is outside the expected {settings.empty_cylinder_weight_kg:.1f} to "
                             f"{settings.full_weight_kg:.1f} kg. Check the cylinder specifications and calibration."))

    jump = _recent_jump(recent, now, settings.abnormal_delta_kg)
    if jump is not None:
        when, delta = jump
        if delta >= settings.refill_min_kg:
            out.append(Alert("refill_detected", "info", "Cylinder refilled or replaced",
                             f"Weight rose by {delta:.1f} kg at {when:%H:%M:%S}."))
        else:
            direction = "rose" if delta > 0 else "dropped"
            out.append(Alert("abnormal_change", "warning", "Abnormal weight change",
                             f"Weight {direction} by {abs(delta):.2f} kg at {when:%H:%M:%S}. "
                             f"Check that the cylinder was not moved or the sensor disturbed."))

    out.sort(key=lambda a: _LEVEL_ORDER[a.level])
    return out
