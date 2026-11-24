"""Source-independent reading model, serial-line parser and the source manager.

Every data source (Wokwi, physical Arduino, demo generator) produces `Reading`
objects. The `SourceManager` runs exactly one source in a background thread,
stores its readings in SQLite and exposes a status snapshot to the UI. Swapping
a source never touches the dashboard code.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

SENSOR_OK = "connected"
SENSOR_ERROR = "error"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Reading:
    """One sensor reading in the standard interface shared by all sources.

    `weight` is the value exactly as delivered by the source (kg). Calibration
    and gas calculations are applied later, at read time (see analytics.py).
    `device_remaining` / `device_level` are the values the firmware computed
    itself; they are kept for cross-checking only.
    """

    timestamp: str
    weight: Optional[float]
    source: str
    sensor_status: str = SENSOR_OK
    device_remaining: Optional[float] = None
    device_level: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
# Matches the line printed by the Wokwi sketch:
#   Total Weight: 22.50 kg | Gas Remaining: 7.50 kg | Level: 52.82%
_SKETCH_RE = re.compile(
    r"^\s*Total\s+Weight:\s*(?P<w>[^\s|]+?)\s*kg\s*\|\s*"
    r"Gas\s+Remaining:\s*(?P<r>[^\s|]+?)\s*kg\s*\|\s*"
    r"Level:\s*(?P<l>[^\s|%]+?)\s*%\s*$",
    re.IGNORECASE,
)


def _to_float(value: Any) -> Optional[float]:
    """float() that maps nan / inf / ovf / garbage to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_serial_line(line: str, source: str, timestamp: Optional[str] = None) -> Optional[Reading]:
    """Parse one serial line into a Reading, or return None if not recognised.

    Supported formats:
      1. The sketch's text line (see _SKETCH_RE).
      2. A JSON object with a "weight" key, e.g. {"weight": 18.5} (for future firmware).
    """
    text = line.strip()
    if not text:
        return None
    stamp = timestamp or now_iso()

    match = _SKETCH_RE.match(text)
    if match:
        weight = _to_float(match["w"])
        return Reading(
            timestamp=stamp,
            weight=weight,
            source=source,
            sensor_status=SENSOR_OK if weight is not None else SENSOR_ERROR,
            device_remaining=_to_float(match["r"]),
            device_level=_to_float(match["l"]),
        )

    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        if isinstance(obj, dict) and "weight" in obj:
            weight = _to_float(obj["weight"])
            default_status = SENSOR_OK if weight is not None else SENSOR_ERROR
            return Reading(
                timestamp=stamp,
                weight=weight,
                source=source,
                sensor_status=str(obj.get("sensor_status", default_status)),
                device_remaining=_to_float(obj.get("remaining")),
                device_level=_to_float(obj.get("level")),
            )
    return None


class LineBuffer:
    """Accumulates raw bytes and yields complete text lines."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[str]:
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        if len(self._buf) > 65536:  # runaway garbage without newlines
            self._buf = b""
        return [chunk.decode("utf-8", "ignore").strip() for chunk in lines]

    def clear(self) -> None:
        self._buf = b""


def backdate(readings: list[Reading], interval_s: float = 1.0, end: Optional[datetime] = None) -> None:
    """Spread a batch of readings backwards in time, the last one at `end` (now).

    Pasted or file-imported lines carry no timestamps; the sketch prints about
    one line per second, so this reconstructs a plausible timeline.
    """
    end = end or datetime.now()
    count = len(readings)
    for index, reading in enumerate(readings):
        moment = end - timedelta(seconds=(count - 1 - index) * interval_s)
        reading.timestamp = moment.isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Source interface
# --------------------------------------------------------------------------
class SourceError(Exception):
    """A source could not open or lost its connection. The message is shown to the user."""


class BaseSource(ABC):
    """Replaceable communication layer. Implement open/read/close and nothing else changes."""

    tag = "unknown"      # value stored in readings.source
    streaming = True     # False: silence is normal (e.g. pasted data)

    def __init__(self) -> None:
        self.parsed_count = 0
        self.unparsed_count = 0
        self.last_unparsed = ""

    @abstractmethod
    def describe(self) -> str:
        """Short human description, e.g. 'COM3 @ 9600 baud'."""

    def open(self) -> None:
        """Open the connection. Raise SourceError with a helpful message on failure."""

    @abstractmethod
    def read(self) -> Optional[Reading]:
        """Return the next reading, or None if nothing arrived. Must return within ~1 s."""

    def close(self) -> None:
        """Release resources. Must not raise."""

    def diagnostics(self) -> dict:
        return {
            "parsed": self.parsed_count,
            "unparsed": self.unparsed_count,
            "last_unparsed": self.last_unparsed,
        }

    def _parse(self, line: str) -> Optional[Reading]:
        text = line.strip()
        if not text:
            return None
        reading = parse_serial_line(text, self.tag)
        if reading is None:
            self.unparsed_count += 1
            self.last_unparsed = text[:200]
        else:
            self.parsed_count += 1
        return reading


def build_source(settings, db) -> BaseSource:
    """Create the source for the currently selected mode (imports are lazy on purpose)."""
    mode = settings.data_source
    if mode == "demo":
        from demo_generator import DemoSource, ensure_history

        ensure_history(db, settings)
        last = db.latest("demo")
        if last is not None and last.weight is not None:
            start = last.weight
        else:
            start = settings.empty_cylinder_weight_kg + settings.cylinder_capacity_kg * 0.8
        return DemoSource(
            start_weight=start,
            empty_weight=settings.empty_cylinder_weight_kg,
            capacity=settings.cylinder_capacity_kg,
            drain_kg_per_hour=settings.demo_drain_kg_per_hour,
            interval_s=settings.demo_interval_s,
        )
    if mode == "wokwi":
        from wokwi_connector import build_wokwi_source

        return build_wokwi_source(settings)
    from arduino_connector import ArduinoSource

    return ArduinoSource(port=settings.serial_port.strip() or None, baud=settings.baud_rate)


# --------------------------------------------------------------------------
# Manager
# --------------------------------------------------------------------------
class SourceManager:
    """Runs one source in a background thread and stores what it delivers."""

    def __init__(self, db, settings) -> None:
        self.db = db
        self._settings = settings
        self._lock = threading.RLock()
        self._control = threading.Lock()  # serialises start/stop/restart
        self._thread: Optional[threading.Thread] = None
        self._stop: Optional[threading.Event] = None
        self._source: Optional[BaseSource] = None
        self._state = "stopped"
        self._message = ""
        self._latest: Optional[Reading] = None
        self._last_rx: Optional[float] = None
        self._connected_at: Optional[float] = None
        self._last_store = 0.0

    # -- control -------------------------------------------------------------
    def start(self) -> None:
        self._swap(build=True)

    def restart(self) -> None:
        self._swap(build=True)

    def stop(self) -> None:
        self._swap(build=False)
        with self._lock:
            self._state = "stopped"
            self._message = "Stopped."

    def configure(self, settings) -> None:
        """Apply new settings; restart the source only if connection-relevant fields changed."""
        with self._lock:
            changed = settings.signature() != self._settings.signature()
            self._settings = settings
        if changed:
            self._swap(build=True)

    @property
    def source(self) -> Optional[BaseSource]:
        return self._source

    # -- status --------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            src = self._source
            now = time.time()
            return {
                "mode": self._settings.data_source,
                "tag": src.tag if src else None,
                "state": self._state,
                "message": self._message,
                "latest": self._latest,
                "age_s": None if self._last_rx is None else now - self._last_rx,
                "connected_for_s": None if self._connected_at is None else now - self._connected_at,
                "streaming": src.streaming if src else True,
                "diagnostics": src.diagnostics() if src else {},
                "source_label": src.describe() if src else "",
            }

    # -- internals -----------------------------------------------------------
    def _swap(self, build: bool) -> None:
        """Stop the running source (joined outside the state lock) and optionally start a new one."""
        with self._control:
            with self._lock:
                old_stop, old_thread = self._stop, self._thread
                self._stop = self._thread = None
                if old_stop is not None:
                    old_stop.set()
            if old_thread is not None and old_thread.is_alive() and old_thread is not threading.current_thread():
                old_thread.join(timeout=3.0)  # lets a serial port close before it is reopened
            if not build:
                return
            try:
                source = build_source(self._settings, self.db)
            except Exception as exc:  # building must never take the app down
                with self._lock:
                    self._source = None
                    self._state = "error"
                    self._message = f"Could not create the data source: {exc}"
                return
            stop = threading.Event()
            thread = threading.Thread(target=self._run, args=(source, stop), daemon=True, name="gg-source")
            with self._lock:
                self._source = source
                self._stop = stop
                self._thread = thread
                self._latest = None
                self._last_rx = None
                self._connected_at = None
                self._last_store = 0.0
                self._state = "connecting"
                self._message = f"Starting {source.describe()}..."
            thread.start()

    def _set_state(self, source: BaseSource, state: str, message: str) -> None:
        with self._lock:
            if self._source is not source:
                return
            self._state = state
            self._message = message
            if state == "connected":
                self._connected_at = time.time()
            elif state != "connected":
                self._connected_at = None

    def _run(self, source: BaseSource, stop: threading.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                self._set_state(source, "connecting", f"Opening {source.describe()}...")
                source.open()
                self._set_state(source, "connected", source.describe())
                backoff = 1.0
                while not stop.is_set():
                    reading = source.read()
                    if reading is not None:
                        self._handle(reading, source, stop)
            except SourceError as exc:
                self._set_state(source, "error", str(exc))
            except Exception as exc:  # unexpected: report, then retry
                self._set_state(source, "error", f"Unexpected error: {exc!r}")
            finally:
                try:
                    source.close()
                except Exception:
                    pass
            if stop.wait(backoff):
                break
            backoff = min(backoff * 2, 10.0)

    def _handle(self, reading: Reading, source: BaseSource, stop: threading.Event) -> None:
        if stop.is_set():
            return
        now = time.time()
        with self._lock:
            if self._source is not source:
                return
            self._latest = reading
            self._last_rx = now
            interval = self._settings.store_interval_s
            due = (not source.streaming) or (now - self._last_store >= interval)
            if due:
                self._last_store = now
        if due:
            try:
                self.db.insert(reading)
            except Exception as exc:
                self._set_state(source, "error", f"Database write failed: {exc}")
