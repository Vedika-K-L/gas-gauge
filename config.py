"""Central configuration: paths, constants, theme palettes and persisted user settings."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "gas_history.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

APP_NAME = "GAS GAUGE"
APP_SUBTITLE = "SMART LPG MONITORING SYSTEM"
APP_VERSION = "1.0.0"

# --- Operating modes -------------------------------------------------------
# "tag" is the value stored in the database `source` column. Every query is
# filtered by it, so demo, Wokwi and hardware readings can never mix.
MODES = {
    "demo": {"label": "DEMO MODE", "short": "DEMO", "tag": "demo"},
    "wokwi": {"label": "WOKWI SIMULATION", "short": "WOKWI", "tag": "wokwi"},
    "hardware": {"label": "PHYSICAL HARDWARE", "short": "HARDWARE", "tag": "arduino"},
}
SOURCE_TAG = {key: meta["tag"] for key, meta in MODES.items()}

WOKWI_TRANSPORTS = {
    "rfc2217": "Wokwi for VS Code - serial bridge (rfc2217)",
    "logfile": "Serial log file - tail a text file",
    "paste": "Paste text from the Wokwi serial monitor",
}

BAUD_RATES = [9600, 19200, 38400, 57600, 115200]

# --- Time ranges ------------------------------------------------------------
TIME_RANGES = {
    "1H": timedelta(hours=1),
    "6H": timedelta(hours=6),
    "12H": timedelta(hours=12),
    "24H": timedelta(hours=24),
    "7D": timedelta(days=7),
}
# Down-sampling bin for the line charts, and bucket size for consumption bars.
RANGE_BIN = {"1H": "10s", "6H": "1min", "12H": "2min", "24H": "5min", "7D": "15min"}
RANGE_BUCKET = {"1H": "15min", "6H": "h", "12H": "h", "24H": "h", "7D": "D"}
BUCKET_LABEL = {"15min": "PER 15 MIN", "h": "PER HOUR", "D": "PER DAY"}

# --- Theme palettes ---------------------------------------------------------
THEMES = {
    "dark": {
        "bg": "#111312",
        "surface": "#1a1d1b",
        "surface2": "#222623",
        "border": "#2e3430",
        "text": "#ecefe8",
        "muted": "#8d9791",
        "grid": "#262b28",
        "track": "#262c28",
        "forest": "#2f9e63",
        "forest_deep": "#1f6b43",
        "lime": "#c6f135",
        "amber": "#f2a93b",
        "red": "#d0605c",
        "shadow": "0 8px 28px rgba(0,0,0,.35)",
        # glassmorphism + ambient lighting
        "glass_hi": "rgba(255,255,255,.075)",
        "glass_lo": "rgba(255,255,255,.012)",
        "glass_edge": "rgba(255,255,255,.12)",
        "glass_shade": "rgba(0,0,0,.38)",
        "glow_a": "rgba(47,158,99,.26)",
        "glow_b": "rgba(198,241,53,.10)",
    },
    "light": {
        "bg": "#f4f1ea",
        "surface": "#fbfaf6",
        "surface2": "#efebe1",
        "border": "#dcd6c8",
        "text": "#1a1d1b",
        "muted": "#6b736e",
        "grid": "#e6e1d4",
        "track": "#e4dfd1",
        "forest": "#1f7a4d",
        "forest_deep": "#17603c",
        "lime": "#8fb81a",
        "amber": "#c98512",
        "red": "#b5443f",
        "shadow": "0 6px 22px rgba(60,50,20,.10)",
        "glass_hi": "rgba(255,255,255,.70)",
        "glass_lo": "rgba(255,255,255,.28)",
        "glass_edge": "rgba(255,255,255,.95)",
        "glass_shade": "rgba(90,70,30,.14)",
        "glow_a": "rgba(31,122,77,.16)",
        "glow_b": "rgba(143,184,26,.16)",
    },
}


@dataclass
class Settings:
    """All user-editable settings. Persisted to data/settings.json."""

    # Data source: "demo" | "wokwi" | "hardware"
    data_source: str = "demo"

    # Cylinder. Defaults are the example values used in the Wokwi sketch.
    cylinder_capacity_kg: float = 14.2
    empty_cylinder_weight_kg: float = 15.0
    # Dashboard-side calibration, applied to PHYSICAL HARDWARE readings only:
    #   calibrated_kg = raw_kg * calibration_factor + tare_offset_kg
    # 1.0 / 0.0 is a neutral pass-through, not a real calibration value.
    calibration_factor: float = 1.0
    tare_offset_kg: float = 0.0
    last_refill_date: str = ""  # YYYY-MM-DD, blank = auto-detect

    # Wokwi connection
    wokwi_transport: str = "rfc2217"
    wokwi_rfc2217_url: str = "rfc2217://localhost:4000"
    wokwi_log_path: str = ""
    wokwi_log_from_start: bool = False
    wokwi_baud_rate: int = 9600

    # Physical hardware connection ("" = auto-detect)
    serial_port: str = ""
    baud_rate: int = 9600

    # Demo generator
    demo_drain_kg_per_hour: float = 0.6
    demo_interval_s: float = 1.0

    # Alert thresholds (defaults mirror the LED thresholds in the sketch)
    medium_pct: float = 60.0
    low_pct: float = 25.0
    critical_pct: float = 10.0
    abnormal_delta_kg: float = 1.5
    refill_min_kg: float = 5.0
    stale_seconds: float = 15.0

    # Runtime
    refresh_seconds: float = 3.0
    store_interval_s: float = 5.0
    retention_days: int = 90
    theme: str = "dark"

    # -- derived -------------------------------------------------------------
    @property
    def full_weight_kg(self) -> float:
        return self.empty_cylinder_weight_kg + self.cylinder_capacity_kg

    @property
    def source_tag(self) -> str:
        return SOURCE_TAG.get(self.data_source, "demo")

    def signature(self) -> tuple:
        """Fields that require the data source to be restarted when changed."""
        mode = self.data_source
        if mode == "demo":
            return (mode, self.demo_interval_s, self.demo_drain_kg_per_hour,
                    self.empty_cylinder_weight_kg, self.cylinder_capacity_kg)
        if mode == "wokwi":
            return (mode, self.wokwi_transport, self.wokwi_rfc2217_url, self.wokwi_log_path,
                    self.wokwi_log_from_start, self.wokwi_baud_rate)
        return (mode, self.serial_port, self.baud_rate)

    # -- validation ----------------------------------------------------------
    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.data_source not in MODES:
            errors.append("Unknown data source.")
        if self.theme not in THEMES:
            errors.append("Unknown theme.")
        if not 0 < self.cylinder_capacity_kg <= 100:
            errors.append("Cylinder capacity must be between 0 and 100 kg.")
        if not 0 <= self.empty_cylinder_weight_kg <= 200:
            errors.append("Empty cylinder weight must be between 0 and 200 kg.")
        if self.calibration_factor <= 0:
            errors.append("Calibration factor must be greater than 0.")
        if not 0 <= self.critical_pct < self.low_pct < self.medium_pct <= 100:
            errors.append("Thresholds must satisfy: 0 <= critical < low < medium <= 100.")
        if self.abnormal_delta_kg <= 0:
            errors.append("Abnormal weight change must be greater than 0 kg.")
        if self.refill_min_kg < self.abnormal_delta_kg:
            errors.append("Refill detection must be at least the abnormal weight change.")
        if self.stale_seconds < 3:
            errors.append("Sensor timeout must be at least 3 seconds.")
        if not 1 <= self.refresh_seconds <= 60:
            errors.append("Refresh interval must be between 1 and 60 seconds.")
        if not 1 <= self.store_interval_s <= 300:
            errors.append("Storage interval must be between 1 and 300 seconds.")
        if self.retention_days < 1:
            errors.append("Retention must be at least 1 day.")
        if self.baud_rate <= 0 or self.wokwi_baud_rate <= 0:
            errors.append("Baud rate must be positive.")
        if self.demo_drain_kg_per_hour < 0 or not 0.2 <= self.demo_interval_s <= 30:
            errors.append("Demo drain must be >= 0 and the demo interval between 0.2 and 30 s.")
        if self.wokwi_transport not in WOKWI_TRANSPORTS:
            errors.append("Unknown Wokwi transport.")
        url = self.wokwi_rfc2217_url.strip()
        if url and not url.lower().startswith(("rfc2217://", "socket://")):
            errors.append("Wokwi bridge URL must start with rfc2217:// or socket://.")
        if self.last_refill_date.strip():
            try:
                date.fromisoformat(self.last_refill_date.strip())
            except ValueError:
                errors.append("Last refill date must be YYYY-MM-DD (or blank).")
        return errors

    # -- persistence ---------------------------------------------------------
    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "Settings":
        defaults = cls()
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defaults
        if not isinstance(raw, dict):
            return defaults
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            default = getattr(defaults, f.name)
            try:
                if isinstance(default, bool):
                    values[f.name] = bool(raw[f.name])
                elif isinstance(default, int):
                    values[f.name] = int(raw[f.name])
                elif isinstance(default, float):
                    values[f.name] = float(raw[f.name])
                else:
                    values[f.name] = str(raw[f.name])
            except (TypeError, ValueError):
                continue
        loaded = cls(**values)
        return loaded if not loaded.validate() else defaults

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({f.name: getattr(self, f.name) for f in fields(self)}, indent=2)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
