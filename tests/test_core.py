"""Backend tests. Run from the gas_gauge folder:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

import alerts  # noqa: E402
import analytics  # noqa: E402
import arduino_connector  # noqa: E402
from config import Settings  # noqa: E402
from data_manager import DataManager  # noqa: E402
from data_source import Reading, SourceManager, parse_serial_line  # noqa: E402
from demo_generator import DemoSource, ensure_history, generate_history  # noqa: E402
from wokwi_connector import WokwiLogFileSource, WokwiPasteSource  # noqa: E402

SKETCH_LINE = "Total Weight: 22.50 kg | Gas Remaining: 7.50 kg | Level: 52.82%"


class ParserTests(unittest.TestCase):
    def test_sketch_line(self):
        r = parse_serial_line(SKETCH_LINE, "wokwi", "2026-11-21T10:30:00")
        self.assertEqual(r.weight, 22.5)
        self.assertEqual(r.device_remaining, 7.5)
        self.assertEqual(r.device_level, 52.82)
        self.assertEqual(r.sensor_status, "connected")
        self.assertEqual(r.source, "wokwi")

    def test_negative_and_crlf(self):
        r = parse_serial_line("Total Weight: -0.01 kg | Gas Remaining: -15.01 kg | Level: 0.00%\r\n", "wokwi")
        self.assertEqual(r.weight, -0.01)

    def test_nan_and_overflow_mean_sensor_error(self):
        for token in ("nan", "inf", "ovf"):
            r = parse_serial_line(f"Total Weight: {token} kg | Gas Remaining: {token} kg | Level: 0.00%", "wokwi")
            self.assertIsNone(r.weight, token)
            self.assertEqual(r.sensor_status, "error")

    def test_json_and_garbage(self):
        self.assertEqual(parse_serial_line('{"weight": 18.5}', "x").weight, 18.5)
        self.assertIsNone(parse_serial_line("HX711 Error!", "x"))
        self.assertIsNone(parse_serial_line("", "x"))
        self.assertIsNone(parse_serial_line("{not json", "x"))


class GasMathTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings(cylinder_capacity_kg=14.2, empty_cylinder_weight_kg=15.0)  # 15 kg empty, 14.2 kg capacity

    def test_formulas(self):
        g = analytics.gas_from_weight(22.1, self.s)
        self.assertAlmostEqual(g.remaining_kg, 7.1)
        self.assertAlmostEqual(g.level_pct, 50.0)
        self.assertFalse(g.out_of_range)

    def test_never_negative_never_above_100(self):
        low = analytics.gas_from_weight(0.0, self.s)
        self.assertEqual(low.remaining_kg, 0.0)
        self.assertEqual(low.level_pct, 0.0)
        self.assertTrue(low.out_of_range)
        high = analytics.gas_from_weight(60.0, self.s)
        self.assertEqual(high.level_pct, 100.0)
        self.assertEqual(high.remaining_kg, self.s.cylinder_capacity_kg)
        self.assertTrue(high.out_of_range)

    def test_none_and_nan(self):
        self.assertIsNone(analytics.gas_from_weight(None, self.s).level_pct)
        self.assertIsNone(analytics.gas_from_weight(float("nan"), self.s).level_pct)

    def test_status_thresholds_match_sketch(self):
        s = self.s
        self.assertEqual(analytics.gas_status(60.01, s)[0], "NORMAL")
        self.assertEqual(analytics.gas_status(60.0, s)[0], "MEDIUM")
        self.assertEqual(analytics.gas_status(25.01, s)[0], "MEDIUM")
        self.assertEqual(analytics.gas_status(25.0, s)[0], "LOW")
        self.assertEqual(analytics.gas_status(10.0, s)[0], "CRITICAL")

    def test_calibration_only_for_hardware(self):
        s = Settings(calibration_factor=2.0, tare_offset_kg=1.0)
        self.assertEqual(analytics.calibrate(10.0, s, "arduino"), 21.0)
        self.assertEqual(analytics.calibrate(10.0, s, "wokwi"), 10.0)
        self.assertEqual(analytics.calibrate(10.0, s, "demo"), 10.0)

    def test_days_remaining(self):
        self.assertAlmostEqual(analytics.estimated_days(6.0, 1.5), 4.0)
        self.assertIsNone(analytics.estimated_days(6.0, 0.0))
        self.assertIsNone(analytics.estimated_days(6.0, None))


class SettingsTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(Settings().validate(), [])
        self.assertTrue(Settings(cylinder_capacity_kg=0).validate())
        self.assertTrue(Settings(critical_pct=30, low_pct=25).validate())
        self.assertTrue(Settings(wokwi_rfc2217_url="http://x").validate())
        self.assertTrue(Settings(last_refill_date="yesterday").validate())

    def test_roundtrip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            Settings(data_source="wokwi", cylinder_capacity_kg=19.0).save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.data_source, "wokwi")
            self.assertEqual(loaded.cylinder_capacity_kg, 19.0)
            path.write_text("{broken")
            self.assertEqual(Settings.load(path), Settings())


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DataManager(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sources_never_mix(self):
        now = datetime.now()
        self.db.insert(Reading(now.isoformat(timespec="seconds"), 20.0, "demo"))
        self.db.insert(Reading(now.isoformat(timespec="seconds"), 25.0, "wokwi"))
        self.assertEqual(self.db.count("demo"), 1)
        self.assertEqual(self.db.latest("wokwi").weight, 25.0)
        self.assertEqual(list(self.db.history("demo")["weight_raw"]), [20.0])
        self.assertIsNone(self.db.latest("arduino"))
        self.assertTrue(self.db.history("arduino").empty)
        self.assertEqual(self.db.clear("demo"), 1)
        self.assertEqual(self.db.count("wokwi"), 1)

    def test_null_weight_and_jumps(self):
        t = datetime(2026, 11, 1, 12, 0, 0)
        weights = [10.0, 10.1, None, 10.2, 18.0, 18.1]
        self.db.insert_many([Reading((t + timedelta(minutes=i)).isoformat(), w, "wokwi",
                                     "connected" if w is not None else "error") for i, w in enumerate(weights)])
        df = self.db.history("wokwi")
        self.assertEqual(len(df), 6)
        self.assertTrue(df["weight_raw"].isna().iloc[2])
        jumps = self.db.find_jumps("wokwi", 5.0)
        self.assertEqual(len(jumps), 1)
        self.assertAlmostEqual(jumps[0][1], 7.8)

    def test_prune_and_history_filter(self):
        old = (datetime.now() - timedelta(days=200)).isoformat(timespec="seconds")
        self.db.insert(Reading(old, 1.0, "demo"))
        self.db.insert(Reading(datetime.now().isoformat(timespec="seconds"), 2.0, "demo"))
        self.assertEqual(self.db.prune(90), 1)
        self.assertEqual(self.db.count("demo"), 1)


class DemoTests(unittest.TestCase):
    def test_history_shape_and_analytics(self):
        s = Settings()
        end = datetime(2026, 11, 21, 12, 0, 0)
        history = generate_history(s.empty_cylinder_weight_kg, s.cylinder_capacity_kg, end=end, seed=1)
        self.assertEqual(history[-1].timestamp, end.isoformat())
        self.assertTrue(all(r.source == "demo" for r in history))
        stamps = [r.timestamp for r in history]
        self.assertEqual(stamps, sorted(stamps))
        weights = [r.weight for r in history]
        self.assertGreaterEqual(min(weights), s.empty_cylinder_weight_kg - 0.05)
        self.assertLessEqual(max(weights), s.full_weight_kg + 0.05)

        with tempfile.TemporaryDirectory() as d:
            db = DataManager(Path(d) / "t.db")
            db.insert_many(history)
            self.assertEqual(len(db.find_jumps("demo", s.refill_min_kg)), 1)
            df = analytics.enrich(db.history("demo"), s, "demo")
            avg = analytics.average_daily(df, s)
            self.assertIsNotNone(avg)
            self.assertTrue(0.8 < avg < 1.8, avg)
            gas = analytics.gas_from_weight(df["weight"].iloc[-1], s)
            metrics = analytics.build_metrics(gas, df, s, end, None)
            self.assertIsNotNone(metrics.days_remaining)
            self.assertGreater(metrics.consumed_today, 0)
            buckets = analytics.consumption_buckets(df, s, "D", end - timedelta(days=7), end)
            self.assertEqual(len(buckets), 8)
            self.assertAlmostEqual(float(buckets.sum()), float(analytics.consumption_series(df, s).sum()), places=6)

    def test_ensure_history_seeds_once(self):
        with tempfile.TemporaryDirectory() as d:
            db = DataManager(Path(d) / "t.db")
            ensure_history(db, Settings())
            n = db.count("demo")
            self.assertGreater(n, 1500)
            ensure_history(db, Settings())
            self.assertEqual(db.count("demo"), n)

    def test_commands(self):
        src = DemoSource(start_weight=25.0, empty_weight=15.0, capacity=14.2, interval_s=0.2, seed=3)
        src.command("jump_to_percent", 10)
        target = 15.0 + 1.42
        for _ in range(200):
            src._next_due = 0
            reading = src.read()
            if src.state()["target_weight"] is None:
                break
        self.assertAlmostEqual(src.state()["weight"], target, places=3)
        self.assertEqual(src.state()["scenario"], "hold")
        src.command("scenario", "sensor_fault")
        src._next_due = 0
        faulty = src.read()
        self.assertIsNone(faulty.weight)
        self.assertEqual(faulty.sensor_status, "error")
        src.command("scenario", "disconnect")
        src._next_due = 0
        self.assertIsNone(src.read())
        with self.assertRaises(ValueError):
            src.command("nope")


class WokwiSourceTests(unittest.TestCase):
    def test_log_file_tail(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "serial.txt"
            path.write_text("old line\n" + SKETCH_LINE + "\n")
            src = WokwiLogFileSource(str(path), from_start=False)
            src.open()
            self.assertIsNone(src.read())  # nothing new yet
            with open(path, "a") as f:
                f.write("Total Weight: 21.00 kg | Gas Remaining: 6.00 kg | Level: 42.25%\n")
                f.write("Total Weight: 20.00 kg | Gas Remain")  # partial line
            first = src.read()
            self.assertEqual(first.weight, 21.0)
            self.assertIsNone(src.read())
            with open(path, "a") as f:
                f.write("ing: 5.00 kg | Level: 35.21%\n")
            self.assertEqual(src.read().weight, 20.0)
            path.write_text(SKETCH_LINE + "\n")  # truncated + rewritten
            self.assertEqual(src.read().weight, 22.5)

    def test_log_file_from_start_backdates(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "serial.txt"
            path.write_text("\n".join(f"Total Weight: {20 + i}.00 kg | Gas Remaining: 1.00 kg | Level: 1.00%" for i in range(5)) + "\n")
            src = WokwiLogFileSource(str(path), from_start=True)
            src.open()
            got = [src.read() for _ in range(5)]
            stamps = [r.timestamp for r in got]
            self.assertEqual(stamps, sorted(stamps))
            self.assertEqual(len(set(stamps)), 5)

    def test_paste(self):
        src = WokwiPasteSource()
        accepted, ignored = src.push_text(f"hello\n{SKETCH_LINE}\n\n{SKETCH_LINE}\n")
        self.assertEqual((accepted, ignored), (2, 1))
        a, b = src.read(), src.read()
        self.assertLess(a.timestamp, b.timestamp)
        self.assertIsNone(src.read())
        self.assertEqual(src.diagnostics()["last_unparsed"], "hello")

    def test_missing_file_is_a_clear_error(self):
        from data_source import SourceError
        with self.assertRaises(SourceError) as ctx:
            WokwiLogFileSource("/no/such/file.txt").open()
        self.assertIn("not found", str(ctx.exception))


class ArduinoTests(unittest.TestCase):
    def test_works_without_pyserial_or_hardware(self):
        ports = arduino_connector.list_serial_ports()
        self.assertIsInstance(ports, list)
        if not arduino_connector.pyserial_available():
            from data_source import SourceError
            with self.assertRaises(SourceError) as ctx:
                arduino_connector.ArduinoSource().open()
            self.assertIn("pip install pyserial", str(ctx.exception))


class ManagerTests(unittest.TestCase):
    def _runtime_parts(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        db = DataManager(Path(tmp.name) / "t.db")
        settings = Settings(demo_interval_s=0.2, store_interval_s=1, **kw)
        return tmp, db, settings

    def test_demo_runs_stores_and_switches(self):
        tmp, db, settings = self._runtime_parts()
        mgr = SourceManager(db, settings)
        try:
            mgr.start()
            time.sleep(2.6)
            snap = mgr.snapshot()
            self.assertEqual(snap["state"], "connected")
            self.assertIsNotNone(snap["latest"])
            self.assertEqual(snap["latest"].source, "demo")
            conn = alerts.connection_summary(snap, settings)
            self.assertEqual(conn.code, "demo")
            seeded = db.count("demo")
            self.assertGreater(seeded, 1500)
            # switch to a Wokwi log file that does not exist -> clear error, demo data untouched
            mgr.configure(Settings(**{**settings.__dict__, "data_source": "wokwi",
                                      "wokwi_transport": "logfile", "wokwi_log_path": "/nope.txt"}))
            time.sleep(0.8)
            snap = mgr.snapshot()
            self.assertEqual(snap["state"], "error")
            self.assertIn("not found", snap["message"])
            self.assertEqual(db.count("wokwi"), 0)
            self.assertEqual(alerts.connection_summary(snap, settings).code, "error")
        finally:
            mgr.stop()
            tmp.cleanup()

    def test_wokwi_paste_flows_into_db(self):
        tmp, db, settings = self._runtime_parts(data_source="wokwi", wokwi_transport="paste")
        mgr = SourceManager(db, settings)
        try:
            mgr.start()
            time.sleep(0.6)
            self.assertEqual(alerts.connection_summary(mgr.snapshot(), settings).code, "ready")
            mgr.source.push_text("\n".join(SKETCH_LINE for _ in range(4)))
            time.sleep(2.5)
            self.assertEqual(db.count("wokwi"), 4)
            self.assertEqual(db.count("demo"), 0)
            snap = mgr.snapshot()
            self.assertEqual(snap["latest"].weight, 22.5)
            self.assertEqual(alerts.connection_summary(snap, settings).code, "imported")
        finally:
            mgr.stop()
            tmp.cleanup()


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.s = Settings(cylinder_capacity_kg=14.2, empty_cylinder_weight_kg=15.0)
        self.now = datetime(2026, 11, 21, 12, 0, 0)

    def snap(self, **kw):
        base = {"mode": "wokwi", "state": "connected", "message": "", "latest": Reading("t", 22.0, "wokwi"),
                "age_s": 1.0, "connected_for_s": 60.0, "streaming": True, "source_label": "x", "diagnostics": {}}
        base.update(kw)
        return base

    def codes(self, snap, weight, recent=None):
        conn = alerts.connection_summary(snap, self.s)
        gas = analytics.gas_from_weight(weight, self.s)
        recent = analytics.enrich(recent if recent is not None else pd.DataFrame(
            {"ts": pd.to_datetime([]), "weight_raw": []}), self.s, "wokwi")
        return [a.code for a in alerts.evaluate(snap, conn, gas, recent, self.s, self.now)]

    def test_healthy(self):
        self.assertEqual(self.codes(self.snap(), 25.0), [])

    def test_low_and_critical(self):
        self.assertEqual(self.codes(self.snap(), 15.0 + 14.2 * 0.2), ["gas_low"])
        self.assertEqual(self.codes(self.snap(), 15.0 + 14.2 * 0.05), ["gas_critical"])

    def test_sensor_disconnected_and_connection_error(self):
        self.assertIn("sensor_disconnected", self.codes(self.snap(age_s=40.0), 25.0))
        self.assertEqual(self.codes(self.snap(state="error", message="boom"), 25.0)[0], "connection_error")
        faulty = self.snap(latest=Reading("t", None, "wokwi", "error"))
        self.assertIn("sensor_disconnected", self.codes(faulty, None))

    def test_pasted_data_does_not_trigger_disconnect(self):
        self.assertNotIn("sensor_disconnected", self.codes(self.snap(streaming=False, age_s=9999.0), 25.0))

    def test_abnormal_change_and_refill(self):
        def frame(a, b):
            return pd.DataFrame({"ts": [self.now - timedelta(minutes=2), self.now - timedelta(minutes=1)],
                                 "weight_raw": [a, b]})
        self.assertIn("abnormal_change", self.codes(self.snap(), 22.0, frame(25.0, 22.0)))
        self.assertIn("refill_detected", self.codes(self.snap(), 29.0, frame(17.0, 29.0)))
        old = pd.DataFrame({"ts": [self.now - timedelta(hours=2), self.now - timedelta(hours=1)], "weight_raw": [25.0, 20.0]})
        self.assertNotIn("abnormal_change", self.codes(self.snap(), 20.0, old))

    def test_out_of_range(self):
        self.assertIn("out_of_range", self.codes(self.snap(), 0.0))


if __name__ == "__main__":
    unittest.main()

