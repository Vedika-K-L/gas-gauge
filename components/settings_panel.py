"""Settings panel: data source, cylinder and calibration, alert thresholds, display and storage."""
from __future__ import annotations

import streamlit as st

import alerts
import config
from arduino_connector import list_serial_ports, pyserial_available
from components.common import render
from wokwi_connector import WokwiPasteSource


# -- helpers ------------------------------------------------------------------
def _apply(rt, label: str = "Settings saved", **changes) -> None:
    errors = rt.update_settings(**changes)
    if errors:
        for message in errors:
            st.error(message)
        return
    st.toast(label, icon="✅")
    st.rerun()


def _on_mode_change(rt) -> None:
    rt.update_settings(data_source=st.session_state["mode_settings"])


def _import_paste(rt) -> None:
    source = rt.manager.source
    text = st.session_state.get("paste_text", "")
    if not isinstance(source, WokwiPasteSource):
        st.session_state["paste_result"] = ("error", "Set the Wokwi transport to 'Paste' and save first.")
    elif not text.strip():
        st.session_state["paste_result"] = ("error", "Nothing to import. Paste the serial monitor text first.")
    else:
        accepted, ignored = source.push_text(text)
        st.session_state["paste_result"] = (
            "ok" if accepted else "error",
            f"Imported {accepted} reading(s); ignored {ignored} unrecognised line(s).",
        )
        st.session_state["paste_text"] = ""


def _calibrate_factor(rt) -> None:
    s = rt.settings
    latest = rt.db.latest("arduino")
    known = st.session_state.get("known_weight", 0.0)
    if latest is None or latest.weight is None:
        st.session_state["calib_result"] = ("error", "No hardware reading available. Connect the Arduino first.")
    elif abs(latest.weight) < 1e-6 or known <= 0:
        st.session_state["calib_result"] = ("error", "Need a non-zero raw reading and a known weight above 0 kg.")
    else:
        factor = (known - s.tare_offset_kg) / latest.weight
        errors = rt.update_settings(calibration_factor=float(factor))
        st.session_state["calib_result"] = (
            ("error", errors[0]) if errors else ("ok", f"Calibration factor set to {factor:.6f}.")
        )


def _tare(rt) -> None:
    s = rt.settings
    latest = rt.db.latest("arduino")
    if latest is None or latest.weight is None:
        st.session_state["calib_result"] = ("error", "No hardware reading available. Connect the Arduino first.")
        return
    rt.update_settings(tare_offset_kg=float(-latest.weight * s.calibration_factor))
    st.session_state["calib_result"] = ("ok", "Scale zeroed at the current reading.")


def _clear_data(rt) -> None:
    removed = rt.db.clear(rt.settings.source_tag)
    st.session_state["confirm_clear"] = False
    st.session_state["clear_result"] = f"Deleted {removed} stored reading(s) for {config.MODES[rt.settings.data_source]['label']}."


def _flash(key: str) -> None:
    result = st.session_state.pop(key, None)
    if not result:
        return
    if isinstance(result, str):
        st.success(result)
    else:
        (st.success if result[0] == "ok" else st.error)(result[1])


# -- tabs ------------------------------------------------------------------------
def _source_tab(rt, s) -> None:
    st.session_state["mode_settings"] = s.data_source
    st.radio("Data source", list(config.MODES), key="mode_settings", horizontal=True,
             format_func=lambda k: config.MODES[k]["label"], on_change=_on_mode_change, args=(rt,))
    snap = rt.manager.snapshot()
    conn = alerts.connection_summary(snap, s)
    st.caption(f"Status: {conn.label} — {conn.detail}")
    st.divider()

    if s.data_source == "demo":
        _demo_source(rt, s)
    elif s.data_source == "wokwi":
        _wokwi_source(rt, s, snap)
    else:
        _hardware_source(rt, s)


def _demo_source(rt, s) -> None:
    st.caption("Demo mode needs no hardware. Use the DEMO CONTROLS panel on the dashboard to raise or lower the level.")
    with st.form("demo_form"):
        drain = st.number_input("Demo drain rate (kg per hour, accelerated)", 0.0, 50.0, float(s.demo_drain_kg_per_hour), 0.1, format="%.2f")
        interval = st.number_input("Demo reading interval (seconds)", 0.2, 30.0, float(s.demo_interval_s), 0.2, format="%.1f")
        if st.form_submit_button("Save demo settings"):
            _apply(rt, demo_drain_kg_per_hour=float(drain), demo_interval_s=float(interval))
    st.button("Reset demo history", key="reset_demo_settings", on_click=rt.reset_demo,
              help="Delete all demo readings and regenerate a week of history")


def _wokwi_source(rt, s, snap) -> None:
    st.caption("Wokwi runs inside Wokwi, so it never shows up as a COM port. Pick how its serial output reaches this app.")
    transports = list(config.WOKWI_TRANSPORTS)
    with st.form("wokwi_form"):
        transport = st.selectbox("Wokwi transport", transports, index=transports.index(s.wokwi_transport),
                                 format_func=lambda k: config.WOKWI_TRANSPORTS[k])
        url = st.text_input("Serial bridge URL (rfc2217 transport)", s.wokwi_rfc2217_url,
                            help="Example: rfc2217://localhost:4000")
        path = st.text_input("Log file path (log file transport)", s.wokwi_log_path,
                             help="A text file the Wokwi serial output is appended to")
        from_start = st.checkbox("Read the log file from the beginning (otherwise only new lines)", s.wokwi_log_from_start)
        baud = st.selectbox("Wokwi baud rate", config.BAUD_RATES,
                            index=config.BAUD_RATES.index(s.wokwi_baud_rate) if s.wokwi_baud_rate in config.BAUD_RATES else 0)
        if st.form_submit_button("Save Wokwi connection"):
            _apply(rt, wokwi_transport=transport, wokwi_rfc2217_url=url.strip(), wokwi_log_path=path.strip(),
                   wokwi_log_from_start=bool(from_start), wokwi_baud_rate=int(baud))

    with st.expander("How to connect your Wokwi simulation"):
        st.markdown(
            "**Wokwi for VS Code (live):** open the project in VS Code with the Wokwi extension, add "
            "`rfc2217ServerPort = 4000` under `[wokwi]` in `wokwi.toml`, start the simulation, then use the "
            "`rfc2217://localhost:4000` bridge.\n\n"
            "**Browser Wokwi:** the browser cannot expose a serial port. Copy the Serial Monitor text and use the "
            "*Paste* transport, or save it to a text file and use the *log file* transport.\n\n"
            "The expected line is `Total Weight: 22.50 kg | Gas Remaining: 7.50 kg | Level: 52.82%`."
        )

    diag = snap.get("diagnostics", {})
    if diag:
        st.caption(f"Lines understood: {diag.get('parsed', 0)} · ignored: {diag.get('unparsed', 0)}")
        if diag.get("last_unparsed"):
            st.warning(f"Last unrecognised line: {diag['last_unparsed']}")

    if s.wokwi_transport == "paste":
        st.text_area("Paste Wokwi serial monitor text", key="paste_text", height=140,
                     placeholder="Total Weight: 22.50 kg | Gas Remaining: 7.50 kg | Level: 52.82%")
        st.button("Import pasted lines", key="paste_btn", on_click=_import_paste, args=(rt,))
        st.caption("Pasted lines have no timestamps, so they are spaced one second apart, ending now. Importing the same text twice stores it twice.")
        _flash("paste_result")


def _hardware_source(rt, s) -> None:
    st.caption("Arduino Uno + HX711 + load cell over USB. The app runs fine without it connected.")
    if not pyserial_available():
        st.warning("PySerial is not installed in this environment. Run: pip install pyserial")
    ports = list_serial_ports()
    devices = [p["device"] for p in ports]
    options = [""] + devices + ([s.serial_port] if s.serial_port and s.serial_port not in devices else [])
    labels = {"": "AUTO-DETECT (recommended)"}
    for p in ports:
        labels[p["device"]] = f"{p['device']}  ·  {p['description']}" + ("  (likely Arduino)" if p["likely_arduino"] else "")
    with st.form("hardware_form"):
        port = st.selectbox("Serial port", options, index=options.index(s.serial_port) if s.serial_port in options else 0,
                            format_func=lambda k: labels.get(k, f"{k}  (not currently detected)"))
        baud = st.selectbox("Baud rate", config.BAUD_RATES,
                            index=config.BAUD_RATES.index(s.baud_rate) if s.baud_rate in config.BAUD_RATES else 0,
                            help="Must match Serial.begin() in the sketch (9600 in your sketch).")
        if st.form_submit_button("Save hardware connection"):
            _apply(rt, serial_port=port, baud_rate=int(baud))
    st.button("Rescan ports", key="rescan_ports")
    if not ports:
        st.caption("No serial ports found right now.")
    st.caption("Calibration for this mode is on the Cylinder & calibration tab.")


def _cylinder_tab(rt, s) -> None:
    with st.form("cylinder_form"):
        c1, c2 = st.columns(2)
        capacity = c1.number_input("Cylinder capacity - LPG (kg)", 0.1, 100.0, float(s.cylinder_capacity_kg), 0.1, format="%.2f")
        empty = c2.number_input("Empty cylinder weight (kg)", 0.0, 200.0, float(s.empty_cylinder_weight_kg), 0.1, format="%.2f")
        refill = st.text_input("Last refill date (YYYY-MM-DD, blank = detect automatically)", s.last_refill_date)
        if st.form_submit_button("Save cylinder"):
            _apply(rt, cylinder_capacity_kg=float(capacity), empty_cylinder_weight_kg=float(empty),
                   last_refill_date=refill.strip())

    st.divider()
    st.markdown("**Sensor calibration** (physical hardware mode only)")
    st.caption("calibrated kg = raw kg x factor + offset. The defaults (1.0 and 0.0) pass values through unchanged. "
               "They are placeholders, not real calibration values: measure your own load cell.")
    with st.form("calibration_form"):
        c1, c2 = st.columns(2)
        factor = c1.number_input("Calibration factor", 0.000001, 1000000.0, float(s.calibration_factor), 0.001, format="%.6f")
        offset = c2.number_input("Tare offset (kg)", -1000.0, 1000.0, float(s.tare_offset_kg), 0.01, format="%.3f")
        if st.form_submit_button("Save calibration"):
            _apply(rt, calibration_factor=float(factor), tare_offset_kg=float(offset))

    st.caption("Helper: put a known weight on the load cell, then compute the factor from the latest hardware reading.")
    c1, c2, c3 = st.columns([2, 2, 2])
    c1.number_input("Known weight on the scale (kg)", 0.0, 1000.0, 1.0, 0.1, key="known_weight", format="%.3f")
    c2.button("Compute factor from latest reading", key="calib_btn", on_click=_calibrate_factor, args=(rt,))
    c3.button("Zero scale at current reading", key="tare_btn", on_click=_tare, args=(rt,))
    _flash("calib_result")


def _alerts_tab(rt, s) -> None:
    with st.form("alerts_form"):
        c1, c2, c3 = st.columns(3)
        medium = c1.number_input("Normal above (%)", 0.0, 100.0, float(s.medium_pct), 1.0, format="%.0f")
        low = c2.number_input("Low gas warning at or below (%)", 0.0, 100.0, float(s.low_pct), 1.0, format="%.0f")
        critical = c3.number_input("Critical gas at or below (%)", 0.0, 100.0, float(s.critical_pct), 1.0, format="%.0f")
        c4, c5, c6 = st.columns(3)
        abnormal = c4.number_input("Abnormal weight change (kg)", 0.1, 50.0, float(s.abnormal_delta_kg), 0.1, format="%.2f",
                                   help="Alert if weight changes by at least this much between two stored readings.")
        refill = c5.number_input("Refill detected above (kg rise)", 0.1, 100.0, float(s.refill_min_kg), 0.5, format="%.1f")
        stale = c6.number_input("Sensor timeout (seconds)", 3.0, 3600.0, float(s.stale_seconds), 1.0, format="%.0f",
                                help="No readings for this long counts as 'sensor disconnected'.")
        if st.form_submit_button("Save alert settings"):
            _apply(rt, medium_pct=float(medium), low_pct=float(low), critical_pct=float(critical),
                   abnormal_delta_kg=float(abnormal), refill_min_kg=float(refill), stale_seconds=float(stale))


def _display_tab(rt, s) -> None:
    with st.form("display_form"):
        c1, c2, c3 = st.columns(3)
        refresh = c1.number_input("Dashboard refresh (seconds)", 1.0, 60.0, float(s.refresh_seconds), 1.0, format="%.0f")
        store = c2.number_input("Store a reading every (seconds)", 1.0, 300.0, float(s.store_interval_s), 1.0, format="%.0f")
        retention = c3.number_input("Keep history for (days)", 1, 3650, int(s.retention_days), 1)
        if st.form_submit_button("Save display and storage"):
            _apply(rt, refresh_seconds=float(refresh), store_interval_s=float(store), retention_days=int(retention))

    st.divider()
    mode_label = config.MODES[s.data_source]["label"]
    st.caption(f"Stored readings for {mode_label}: {rt.db.count(s.source_tag):,}. Other modes are kept separately.")
    st.checkbox(f"I want to delete all stored readings for {mode_label}", key="confirm_clear")
    st.button("Delete stored readings", key="clear_btn", on_click=_clear_data, args=(rt,),
              disabled=not st.session_state.get("confirm_clear", False))
    _flash("clear_result")


def render_settings(rt) -> None:
    s = rt.settings
    render('<div class="gg-section-title">Settings</div>')
    tab_source, tab_cylinder, tab_alerts, tab_display = st.tabs(
        ["Data source", "Cylinder & calibration", "Alerts", "Display & storage"]
    )
    with tab_source:
        _source_tab(rt, s)
    with tab_cylinder:
        _cylinder_tab(rt, s)
    with tab_alerts:
        _alerts_tab(rt, s)
    with tab_display:
        _display_tab(rt, s)
