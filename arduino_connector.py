"""Physical Arduino connector (Arduino Uno + HX711 + load cell) using PySerial.

Not required to run the dashboard: the module imports PySerial lazily and
reports a clear error if it is missing or no board is connected. The Arduino
is expected to print the same line the Wokwi sketch prints, so the parser is
shared with the Wokwi connector.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

from data_source import BaseSource, LineBuffer, Reading, SourceError

# USB vendor IDs of Arduino boards and the common USB-serial chips on clones.
_KNOWN_VIDS = {0x2341, 0x2A03, 0x1B4F, 0x1A86, 0x0403, 0x10C4}
_KNOWN_WORDS = ("arduino", "ch340", "ch341", "ftdi", "cp210", "usb serial", "usb-serial")


def list_serial_ports() -> list[dict]:
    """Return available serial ports. Empty list if PySerial is missing."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for info in list_ports.comports():
        text = f"{info.description or ''} {info.manufacturer or ''}".lower()
        likely = (info.vid in _KNOWN_VIDS) or any(word in text for word in _KNOWN_WORDS)
        ports.append(
            {
                "device": info.device,
                "description": info.description or "",
                "hwid": info.hwid or "",
                "likely_arduino": bool(likely),
            }
        )
    ports.sort(key=lambda p: (not p["likely_arduino"], p["device"]))
    return ports


def pyserial_available() -> bool:
    try:
        import serial  # noqa: F401
    except ImportError:
        return False
    return True


def detect_arduino_port() -> Optional[str]:
    """First port that looks like an Arduino, or None."""
    for port in list_serial_ports():
        if port["likely_arduino"]:
            return port["device"]
    return None


def _explain_open_error(port: str, exc: Exception) -> str:
    text = str(exc).lower()
    if "permission" in text or "access is denied" in text or "busy" in text:
        return (f"Port {port} is not accessible. Close the Arduino IDE / Serial Monitor or any other "
                f"program using it. On Linux, add your user to the 'dialout' group.")
    if "no such file" in text or "could not open port" in text or "cannot find" in text or "filenotfound" in text:
        return f"Port {port} was not found. Check the USB cable and the port selected in Settings."
    return f"Could not open {port}: {exc}"


class ArduinoSource(BaseSource):
    tag = "arduino"

    def __init__(self, port: Optional[str] = None, baud: int = 9600) -> None:
        super().__init__()
        self.port = port            # None = auto-detect on every (re)connect
        self.baud = baud
        self.active_port: Optional[str] = None
        self._ser = None
        self._lines = LineBuffer()
        self._pending: deque[Reading] = deque()

    def describe(self) -> str:
        shown = self.active_port or self.port or "auto-detect"
        return f"Arduino on {shown} @ {self.baud} baud"

    def open(self) -> None:
        try:
            import serial
        except ImportError:
            raise SourceError("PySerial is not installed. Run: pip install pyserial") from None

        port = self.port or detect_arduino_port()
        if not port:
            found = ", ".join(p["device"] for p in list_serial_ports()) or "none"
            raise SourceError(
                f"No Arduino detected. Plug the board in over USB or choose the port in Settings. "
                f"Ports found: {found}."
            )
        try:
            self._ser = serial.Serial(port, self.baud, timeout=1)
        except (serial.SerialException, OSError, ValueError) as exc:
            raise SourceError(_explain_open_error(port, exc)) from None
        self.active_port = port
        time.sleep(2.0)  # an Uno resets when the port is opened; let it boot
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        self._lines.clear()

    def read(self) -> Optional[Reading]:
        if self._pending:
            return self._pending.popleft()
        if self._ser is None:
            raise SourceError("Serial port is not open.")
        try:
            data = self._ser.read(max(1, self._ser.in_waiting))
        except Exception as exc:
            raise SourceError(f"Lost connection to {self.active_port}: {exc}. Check the USB cable.") from None
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
