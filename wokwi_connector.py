"""Wokwi connector.

Wokwi runs the Arduino simulation inside Wokwi (browser or VS Code); it does NOT
appear as a COM port on this computer. Three configurable bridges are provided:

  rfc2217  Wokwi for VS Code can forward the simulated serial port over a local
           TCP port (rfc2217ServerPort in wokwi.toml). PySerial reads it with an
           rfc2217://host:port URL. This is the only fully live option.
  logfile  Tails a text file that you append the serial output to.
  paste    You paste text from the Wokwi serial monitor into the dashboard.

All three feed the same parser, so the rest of the app is unaware of the bridge.
"""
from __future__ import annotations

import os
import queue
import time
from collections import deque
from datetime import datetime
from typing import Optional

from data_source import BaseSource, LineBuffer, Reading, SourceError, backdate


class WokwiRfc2217Source(BaseSource):
    tag = "wokwi"

    def __init__(self, url: str, baud: int = 9600) -> None:
        super().__init__()
        self.url = url.strip()
        self.baud = baud
        self._ser = None
        self._lines = LineBuffer()
        self._pending: deque[Reading] = deque()

    def describe(self) -> str:
        return f"Wokwi serial bridge {self.url or '(not configured)'}"

    def open(self) -> None:
        if not self.url:
            raise SourceError("No Wokwi bridge URL configured. Enter one in Settings > Data source.")
        try:
            import serial
        except ImportError:
            raise SourceError("PySerial is not installed. Run: pip install pyserial") from None
        try:
            self._ser = serial.serial_for_url(self.url, baudrate=self.baud, timeout=1)
        except Exception as exc:
            raise SourceError(
                f"Could not reach the Wokwi serial bridge at {self.url}. Start the simulation in "
                f"VS Code with rfc2217ServerPort set in wokwi.toml, or switch the Wokwi transport "
                f"to log file / paste. ({exc})"
            ) from None
        self._lines.clear()

    def read(self) -> Optional[Reading]:
        if self._pending:
            return self._pending.popleft()
        if self._ser is None:
            raise SourceError("Wokwi serial bridge is not open.")
        try:
            data = self._ser.read(max(1, getattr(self._ser, "in_waiting", 0) or 1))
        except Exception as exc:
            raise SourceError(f"Lost the Wokwi serial bridge: {exc}") from None
        if not data:
            return None
        for line in self._lines.feed(data):
            reading = self._parse(line)
            if reading is not None:
                self._pending.append(reading)
        return self._pending.popleft() if self._pending else None

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


class WokwiLogFileSource(BaseSource):
    tag = "wokwi"

    def __init__(self, path: str, from_start: bool = False) -> None:
        super().__init__()
        self.path = path.strip()
        self.from_start = from_start
        self._pos = 0
        self._lines = LineBuffer()
        self._pending: deque[Reading] = deque()

    def describe(self) -> str:
        return f"Wokwi log file {self.path or '(not configured)'}"

    def open(self) -> None:
        if not self.path:
            raise SourceError("No log file path configured. Enter one in Settings > Data source.")
        if not os.path.isfile(self.path):
            raise SourceError(f"Log file not found: {self.path}")
        try:
            self._pos = 0 if self.from_start else os.path.getsize(self.path)
        except OSError as exc:
            raise SourceError(f"Cannot read log file: {exc}") from None
        self._lines.clear()
        self._pending.clear()

    def read(self) -> Optional[Reading]:
        if self._pending:
            return self._pending.popleft()
        try:
            size = os.path.getsize(self.path)
        except OSError as exc:
            raise SourceError(f"Cannot read log file: {exc}") from None
        if size < self._pos:  # truncated or replaced
            self._pos = 0
            self._lines.clear()
        if size > self._pos:
            try:
                with open(self.path, "rb") as handle:
                    handle.seek(self._pos)
                    chunk = handle.read(1 << 20)
            except OSError as exc:
                raise SourceError(f"Cannot read log file: {exc}") from None
            self._pos += len(chunk)
            batch = [r for r in (self._parse(line) for line in self._lines.feed(chunk)) if r is not None]
            if len(batch) > 1:
                backdate(batch)
            self._pending.extend(batch)
            if self._pending:
                return self._pending.popleft()
        time.sleep(0.4)
        return None


class WokwiPasteSource(BaseSource):
    """Receives text pasted in the dashboard (Settings > Data source)."""

    tag = "wokwi"
    streaming = False

    def __init__(self) -> None:
        super().__init__()
        self._queue: "queue.Queue[Reading]" = queue.Queue()

    def describe(self) -> str:
        return "Wokwi pasted serial text"

    def push_text(self, text: str, interval_s: float = 1.0) -> tuple[int, int]:
        """Parse pasted text. Returns (accepted_lines, ignored_lines)."""
        readings: list[Reading] = []
        ignored = 0
        for line in text.splitlines():
            if not line.strip():
                continue
            reading = self._parse(line)
            if reading is None:
                ignored += 1
            else:
                readings.append(reading)
        backdate(readings, interval_s=interval_s, end=datetime.now())
        for reading in readings:
            self._queue.put(reading)
        return len(readings), ignored

    def read(self) -> Optional[Reading]:
        try:
            return self._queue.get(timeout=0.5)
        except queue.Empty:
            return None


def build_wokwi_source(settings) -> BaseSource:
    transport = settings.wokwi_transport
    if transport == "logfile":
        return WokwiLogFileSource(settings.wokwi_log_path, settings.wokwi_log_from_start)
    if transport == "paste":
        return WokwiPasteSource()
    return WokwiRfc2217Source(settings.wokwi_rfc2217_url, settings.wokwi_baud_rate)
