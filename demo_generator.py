"""Demo mode: realistic simulated readings. Always stored with source = 'demo'."""
from __future__ import annotations

import config

import math
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from data_source import SENSOR_ERROR, SENSOR_OK, BaseSource, Reading

RAMP_KG_PER_READING = 0.2

SCENARIOS = {
    "normal": "Normal use (accelerated drain)",
    "fast_drain": "Fast drain (x20)",
    "hold": "Hold steady",
    "refill": "Refill (gas level rises)",
    "sensor_fault": "Sensor fault (no valid weight)",
    "disconnect": "Sensor disconnected (no data)",
}


class DemoSource(BaseSource):
    tag = "demo"
    streaming = True

    def __init__(self, start_weight: float, empty_weight: float, capacity: float,
                 drain_kg_per_hour: float = 0.6, interval_s: float = 1.0, seed: Optional[int] = None) -> None:
        super().__init__()
        self.empty = empty_weight
        self.full = empty_weight + capacity
        self.drain = drain_kg_per_hour
        self.interval = interval_s
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._weight = min(max(start_weight, self.empty), self.full + 0.3)
        self._scenario = "normal"
        self._target: Optional[float] = None
        # Added on top of the simulated weight, never clamped: a bumped or lifted cylinder can read
        # below the empty weight, so a spike must stay visible even when the cylinder is nearly empty.
        self._offset = 0.0
        self._next_due = 0.0
        self._last_emit: Optional[float] = None

    def describe(self) -> str:
        return "Demo data"

    # -- controls used by the dashboard ---------------------------------------
    def command(self, name: str, value: Optional[float] = None) -> None:
        with self._lock:
            if name == "scenario" and value in SCENARIOS:
                self._scenario = value  # type: ignore[assignment]
                self._target = None
                self._offset = 0.0
            elif name == "jump_to_percent" and value is not None:
                pct = min(max(float(value), 0.0), 100.0)
                self._target = self.empty + (self.full - self.empty) * pct / 100.0
                self._offset = 0.0
            elif name == "spike" and value is not None:
                self._offset += float(value)
            else:
                raise ValueError(f"Unknown demo command: {name!r}")

    def state(self) -> dict:
        with self._lock:
            return {"scenario": self._scenario, "target_weight": self._target, "weight": self._weight}

    # -- BaseSource ------------------------------------------------------------
    def read(self) -> Optional[Reading]:
        now = time.monotonic()
        wait = self._next_due - now
        if wait > 0:
            time.sleep(min(wait, 0.25))
            return None
        dt = self.interval if self._last_emit is None else min(now - self._last_emit, self.interval * 3)
        self._last_emit = now
        self._next_due = now + self.interval

        with self._lock:
            scenario = self._scenario
            self._advance(dt)
            weight = self._weight + self._offset
        stamp = config.now().isoformat(timespec="seconds")
        if scenario == "disconnect":
            return None
        if scenario == "sensor_fault":
            return Reading(stamp, None, self.tag, SENSOR_ERROR)
        return Reading(stamp, round(weight + self._rng.gauss(0, 0.003), 3), self.tag, SENSOR_OK)

    def _advance(self, dt: float) -> None:
        if self._target is not None:
            step = max(-RAMP_KG_PER_READING, min(RAMP_KG_PER_READING, self._target - self._weight))
            self._weight += step
            if abs(self._target - self._weight) < 1e-6:
                self._target = None
                self._scenario = "hold"
        elif self._scenario == "normal":
            self._weight -= self.drain / 3600.0 * dt * (1 + 0.3 * math.sin(time.time() / 37.0))
        elif self._scenario == "fast_drain":
            self._weight -= self.drain / 3600.0 * dt * 20
        elif self._scenario == "refill":
            self._weight += RAMP_KG_PER_READING
            if self._weight >= self.full:
                self._weight = self.full
                self._scenario = "hold"
        self._weight = min(max(self._weight, self.empty), self.full + 0.3)


# --------------------------------------------------------------------------
# Seed history
# --------------------------------------------------------------------------
def _usage_rate(hour: float) -> float:
    """kg per hour for a household: breakfast, lunch and dinner peaks."""
    if 7 <= hour < 9:
        return 0.18
    if 12 <= hour < 14:
        return 0.15
    if 19 <= hour < 21:
        return 0.25
    return 0.004


def generate_history(empty: float, capacity: float, days: int = 7, step_minutes: int = 5,
                     end: Optional[datetime] = None, seed: Optional[int] = None) -> list[Reading]:
    """A week of plausible consumption with one cylinder change half-way through.

    Roughly 1.2 kg/day; starts low, the cylinder is swapped for a full one at the
    mid-point, so the 7D charts, refill detection and averages all have data.
    """
    rng = random.Random(seed)
    end = (end or config.now()).replace(microsecond=0)
    start = end - timedelta(days=days)
    swap_at = start + timedelta(days=days / 2)
    weight = empty + capacity * 0.35
    swapped = False
    readings: list[Reading] = []
    for i in range(int(days * 24 * 60 / step_minutes) + 1):
        moment = start + timedelta(minutes=i * step_minutes)
        if not swapped and moment >= swap_at:
            weight = empty + capacity * rng.uniform(0.985, 1.0)
            swapped = True
        else:
            rate = _usage_rate(moment.hour + moment.minute / 60.0)
            weight -= rate * (step_minutes / 60.0) * rng.uniform(0.85, 1.15)
            weight = max(weight, empty)
        readings.append(
            Reading(moment.isoformat(timespec="seconds"), round(weight + rng.gauss(0, 0.004), 3), "demo", SENSOR_OK)
        )
    return readings


def ensure_history(db, settings) -> None:
    """Seed demo history once, so charts are populated the first time demo mode is used."""
    if db.count("demo") == 0:
        db.insert_many(
            generate_history(settings.empty_cylinder_weight_kg, settings.cylinder_capacity_kg)
        )
