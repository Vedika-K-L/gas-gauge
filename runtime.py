"""Process-wide runtime: settings, database and the background source manager.

Under Streamlit this is created once (st.cache_resource) and shared by every
browser session, so the reader thread keeps running between page refreshes.
"""
from __future__ import annotations

import dataclasses
import threading

import config
from config import Settings
from data_manager import DataManager
from data_source import SourceManager


class Runtime:
    def __init__(self, settings_path=None, db_path=None) -> None:
        self._settings_path = settings_path or config.SETTINGS_PATH
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.settings: Settings = Settings.load(self._settings_path)
        self.db = DataManager(db_path or config.DB_PATH)
        self.db.prune(self.settings.retention_days)
        self.manager = SourceManager(self.db, self.settings)
        self._lock = threading.Lock()
        self.manager.start()

    def update_settings(self, **changes) -> list[str]:
        """Validate, persist and apply. Returns a list of error messages (empty on success)."""
        with self._lock:
            new = dataclasses.replace(self.settings, **changes)
            errors = new.validate()
            if errors:
                return errors
            new.save(self._settings_path)
            self.settings = new
            self.manager.configure(new)
            return []

    def reset_demo(self) -> None:
        """Delete all demo readings and regenerate the demo history."""
        self.db.clear("demo")
        if self.settings.data_source == "demo":
            self.manager.restart()


def _build() -> Runtime:
    return Runtime()


try:  # shared across sessions under Streamlit; plain call elsewhere (tests)
    import streamlit as _st

    get_runtime = _st.cache_resource(show_spinner=False)(_build)
except ImportError:
    get_runtime = _build
