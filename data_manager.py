"""SQLite persistence. Every query is filtered by `source`, so demo / Wokwi / hardware never mix."""
from __future__ import annotations

import config

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from data_source import Reading

_COLUMNS = ["ts", "weight_raw", "sensor_status", "device_remaining", "device_level"]


class DataManager:
    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS readings (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       ts TEXT NOT NULL,
                       source TEXT NOT NULL,
                       weight_raw REAL,
                       sensor_status TEXT NOT NULL,
                       device_remaining REAL,
                       device_level REAL
                   )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_src_ts ON readings(source, ts)")

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return _Connection(conn)

    # -- writes ----------------------------------------------------------------
    def insert(self, reading: Reading) -> None:
        self.insert_many([reading])

    def insert_many(self, readings: Iterable[Reading]) -> None:
        rows = [
            (r.timestamp, r.source, r.weight, r.sensor_status, r.device_remaining, r.device_level)
            for r in readings
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO readings (ts, source, weight_raw, sensor_status, device_remaining, device_level) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def clear(self, source: str) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM readings WHERE source = ?", (source,)).rowcount

    def prune(self, retention_days: int) -> int:
        cutoff = (config.now() - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._connect() as conn:
            return conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,)).rowcount

    # -- reads -----------------------------------------------------------------
    def latest(self, source: str) -> Optional[Reading]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM readings WHERE source = ? ORDER BY ts DESC, id DESC LIMIT 1", (source,)
            ).fetchone()
        if row is None:
            return None
        return Reading(row["ts"], row["weight_raw"], row["source"], row["sensor_status"],
                       row["device_remaining"], row["device_level"])

    def count(self, source: str) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM readings WHERE source = ?", (source,)).fetchone()[0]

    def history(self, source: str, since: Optional[datetime] = None, until: Optional[datetime] = None) -> pd.DataFrame:
        sql = "SELECT ts, weight_raw, sensor_status, device_remaining, device_level FROM readings WHERE source = ?"
        params: list = [source]
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since.isoformat(timespec="seconds"))
        if until is not None:
            sql += " AND ts <= ?"
            params.append(until.isoformat(timespec="seconds"))
        sql += " ORDER BY ts, id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        df = pd.DataFrame([tuple(r) for r in rows], columns=_COLUMNS)
        df["ts"] = pd.to_datetime(df["ts"], format="ISO8601")
        for col in ("weight_raw", "device_remaining", "device_level"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        return df

    def find_jumps(self, source: str, min_raw_delta: float, limit: int = 5) -> list[tuple[str, float]]:
        """Timestamps where the raw weight rose by at least `min_raw_delta` between two samples."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT ts, d FROM (
                       SELECT ts, weight_raw - LAG(weight_raw) OVER (ORDER BY ts, id) AS d
                       FROM readings WHERE source = ? AND weight_raw IS NOT NULL
                   ) WHERE d >= ? ORDER BY ts DESC LIMIT ?""",
                (source, min_raw_delta, limit),
            ).fetchall()
        return [(r["ts"], r["d"]) for r in rows]


class _Connection:
    """Context manager: commit on success, always close."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
