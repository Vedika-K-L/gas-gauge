"""UI smoke test that runs WITHOUT streamlit/plotly installed.

It replaces `streamlit` and `plotly` with small recording fakes, then executes the real
app.py, header, settings panel, demo panel, gauge, cards and chart builders end to end.
It catches Python errors, broken HTML and wiring mistakes. It does NOT prove that real
Streamlit/Plotly render the page correctly: run the app once to check the visuals.
"""
import importlib
import runpy
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- fakes -----
class _State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class FakeStreamlit:
    def __init__(self):
        self.session_state = _State()
        self.html_out, self.markdown_out, self.messages, self.charts = [], [], [], []
        self.widgets = []
        self.buttons = []  # (label, kwargs) for every st.button, so tests can check key / type / icon
        self.query_params = {}
        self.sidebar = _Ctx(self)
        self._resources = {}

    # layout
    def columns(self, spec, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Ctx(self) for _ in range(n)]

    def tabs(self, labels):
        return [_Ctx(self) for _ in labels]

    def expander(self, *a, **k):
        return _Ctx(self)

    form = container = expander

    # output
    def html(self, markup):
        self.html_out.append(markup)

    def markdown(self, text, **kw):
        self.markdown_out.append(text)

    def _msg(kind):
        def fn(self, text, *a, **k):
            self.messages.append((kind, str(text)))
        return fn

    caption, error, success, warning, info, toast = _msg("caption"), _msg("error"), _msg("success"), _msg("warning"), _msg("info"), _msg("toast")

    def divider(self):
        pass

    def set_page_config(self, **kw):
        pass

    def plotly_chart(self, fig, **kw):
        self.charts.append((kw.get("key"), fig))

    def rerun(self):
        raise AssertionError("st.rerun() should not run in a smoke pass without button clicks")

    # widgets: return their current/default value
    def _record(self, kind, label):
        self.widgets.append((kind, label))

    def radio(self, label, options, key=None, **kw):
        self._record("radio", label)
        return self.session_state.get(key, list(options)[0])

    def selectbox(self, label, options, index=0, key=None, **kw):
        self._record("selectbox", label)
        return self.session_state.get(key, list(options)[index])

    def number_input(self, label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
        self._record("number_input", label)
        return self.session_state.get(key, value)

    def checkbox(self, label, value=False, key=None, **kw):
        self._record("checkbox", label)
        return self.session_state.get(key, value)

    def text_input(self, label, value="", **kw):
        self._record("text_input", label)
        return value

    def text_area(self, label, key=None, **kw):
        self._record("text_area", label)
        return self.session_state.get(key, "")

    def slider(self, label, a, b, value=None, key=None, **kw):
        self._record("slider", label)
        return self.session_state.get(key, value)

    def button(self, label, **kw):
        self._record("button", label)
        self.buttons.append((label, kw))
        return False

    form_submit_button = button

    # decorators
    def fragment(self, func=None, **kw):
        return func if func is not None else (lambda f: f)

    def cache_resource(self, func=None, **kw):
        def deco(f):
            def wrapper(*a, **k):
                return self._resources.setdefault(f.__name__, f(*a, **k))
            return wrapper
        return deco(func) if func is not None else deco

    def cache_data(self, func=None, **kw):
        return func if func is not None else (lambda f: f)


class _Ctx:
    """Context manager that also exposes widget methods (e.g. column.number_input)."""

    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return getattr(self._st, name)


class FakeFigure:
    def __init__(self, *a, **k):
        self.traces, self.layout, self.annotations, self.hlines = [], {}, [], []

    def add_trace(self, t):
        self.traces.append(t)

    def update_layout(self, **k):
        self.layout.update(k)

    def update_xaxes(self, **k):
        pass

    def update_yaxes(self, **k):
        pass

    def add_annotation(self, **k):
        self.annotations.append(k)

    def add_hline(self, **k):
        self.hlines.append(k)


class _Trace:
    def __init__(self, **k):
        self.kw = k


def install_fakes():
    fake = FakeStreamlit()
    sys.modules["streamlit"] = fake
    go = type(sys)("plotly.graph_objects")
    go.Figure, go.Scatter, go.Bar = FakeFigure, _Trace, _Trace
    plotly = type(sys)("plotly")
    plotly.graph_objects = go
    sys.modules["plotly"], sys.modules["plotly.graph_objects"] = plotly, go
    for name in [m for m in sys.modules if m in ("runtime", "app") or m.startswith("components")]:
        del sys.modules[name]
    return fake


class _Balance(HTMLParser):
    VOID = {"br", "hr", "img", "input", "meta", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> with stack {self.stack[-3:]}")
        else:
            self.stack.pop()


def check_balanced(test, markup):
    parser = _Balance()
    parser.feed(markup)
    parser.close()
    test.assertEqual(parser.errors, [], markup[:200])
    test.assertEqual(parser.stack, [], f"unclosed tags {parser.stack} in {markup[:200]}")


# ---------------------------------------------------------------- tests -----
VIEW_IDS = ["overview", "cylinder", "analytics", "consumption", "alerts", "demo", "settings"]


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = install_fakes()
        import config
        data = Path(self.tmp.name)
        config.DATA_DIR, config.DB_PATH, config.SETTINGS_PATH = data, data / "t.db", data / "s.json"
        runtime = importlib.import_module("runtime")
        self.rt = runtime.get_runtime()

    def tearDown(self):
        self.rt.manager.stop()
        self.tmp.cleanup()

    def run_app(self, view=None):
        """Run app.py once, showing `view` (None = whatever the session already has)."""
        for bucket in (self.st.html_out, self.st.markdown_out, self.st.messages, self.st.charts,
                       self.st.widgets, self.st.buttons):
            bucket.clear()
        if view is not None:
            self.st.session_state["view"] = view
        runpy.run_path(str(ROOT / "app.py"), run_name="app_under_test")
        return "\n".join(self.st.html_out)

    def run_all_views(self):
        """Run every page once. Returns {view: (html, chart keys, widgets, buttons)}."""
        out = {}
        for view in VIEW_IDS:
            page = self.run_app(view)
            self.assert_well_formed()
            out[view] = (page, [k for k, _ in self.st.charts], list(self.st.widgets), list(self.st.buttons))
        return out

    def assert_well_formed(self):
        for markup in self.st.html_out:
            check_balanced(self, markup)

    def test_stats_tiles_and_3d_hint(self):
        import pandas as pd
        from components.live_stats import build_stats_html
        from components import gas_gauge_3d
        s = self.rt.settings
        df = pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=3, freq="min"),
                           "weight": [20.0, 19.5, 19.0], "level_pct": [35.0, 31.0, 27.0]})
        html = build_stats_html(df, s, "1H", True)
        for needle in ("31.0", "1.00", "LIVE"):
            self.assertIn(needle, html)
        self.assertIn("—", build_stats_html(df.iloc[0:0], s, "1H", False))
        self.assertIn("gg-3d-hint", gas_gauge_3d.hint_html())

    def test_demo_mode_page_has_new_ui(self):
        self.rt.update_settings(demo_interval_s=0.2, store_interval_s=1)
        time.sleep(1.0)
        page = self.run_app("analytics")
        self.assertIn("gg-stats", page)
        self.assert_well_formed()

    def test_demo_mode_full_page(self):
        self.rt.update_settings(demo_interval_s=0.2, store_interval_s=1)
        time.sleep(1.2)
        views = self.run_all_views()
        everywhere = "\n".join(v[0] for v in views.values())
        self.assertIn("DEMO MODE", everywhere)
        self.assertIn("GAS GAUGE", everywhere)
        self.assertIn("SMART LPG MONITORING SYSTEM", everywhere)
        overview = views["overview"][0]
        for label in ("Remaining gas", "Consumed today", "Total cylinder weight", "Estimated days left",
                      "Avg daily consumption", "Sensor connection"):
            self.assertIn(label, overview)
        self.assertIn("Cylinder details", views["consumption"][0])
        # each chart lives on exactly one page
        self.assertEqual(views["analytics"][1], ["chart_level", "chart_weight"])
        self.assertEqual(views["consumption"][1], ["chart_consumption"])
        for view in ("overview", "cylinder", "alerts", "demo", "settings"):
            self.assertEqual(views[view][1], [], view)
        self.run_app("analytics")
        for _, fig in self.st.charts:
            self.assertTrue(fig.traces, "chart has no data")
            self.assertEqual(fig.layout.get("height"), 330)
        self.run_app("consumption")
        trace = self.st.charts[0][1].traces[0]
        self.assertEqual(len(trace.kw["y"]), len(trace.kw["x"]))
        css = "\n".join(self.st.markdown_out)
        self.assertIn("--lime:", css)
        self.assertIn(".gg-card", css)
        # ring gauge is plain HTML (no inline <svg>, which some Streamlit versions strip)
        page = overview
        self.assertIn('class="gg-ring"', page)
        self.assertNotIn("<svg", page)
        self.assertIn("gg-ring-arc", page)
        self.assertIn("gg-p", page)
        # logo is an <img> data URI that decodes to valid SVG
        import base64, re
        uri = re.search(r'class="gg-logo"[^>]*src="data:image/svg\+xml;base64,([^"]+)"', page)
        self.assertIsNotNone(uri)
        self.assertEqual(ET.fromstring(base64.b64decode(uri.group(1))).tag.split("}")[-1], "svg")
        # demo controls and the live gauge preview are on the Demo page
        self.assertIn("gg-ring", views["demo"][0])
        self.assertTrue(any("Gas level" in w[1] for w in views["demo"][2]))
        # settings widgets only on the Settings page
        self.assertTrue(any("Data source" in w[1] for w in views["settings"][2]))
        self.assertFalse(any("Cylinder capacity" in w[1] for w in views["overview"][2]))

    def test_all_modes_themes_and_panels_render(self):
        for mode in ("wokwi", "hardware", "demo"):
            for theme in ("light", "dark"):
                errors = self.rt.update_settings(data_source=mode, theme=theme, wokwi_transport="paste")
                self.assertEqual(errors, [])
                time.sleep(0.3)
                views = self.run_all_views()
                self.assertIn(config_label(mode), views["overview"][0])
                self.assertEqual(views["analytics"][1] + views["consumption"][1],
                                 ["chart_level", "chart_weight", "chart_consumption"])
                self.assertTrue(any("Data source" in w[1] for w in views["settings"][2]))
                self.assertFalse([m for m in self.st.messages if m[0] == "error"], self.st.messages)
        # hardware / wokwi with nothing connected: clear message, NO DATA gauge, charts show placeholder
        self.rt.update_settings(data_source="hardware", serial_port="")
        time.sleep(1.2)
        page = self.run_app("overview")
        self.assertIn("NO DATA", page)
        self.assertTrue("ERROR" in page or "CONNECTING" in page)
        self.run_app("analytics")
        self.assertTrue(any(a for a in self.st.charts[0][1].annotations))

    def test_sidebar_navigation(self):
        self.rt.update_settings(data_source="demo")
        for view in VIEW_IDS:
            self.run_app(view)
            nav = {kw["key"]: (label, kw) for label, kw in self.st.buttons if kw.get("key", "").startswith("nav-")}
            self.assertEqual(set(nav), {f"nav-{v}" for v in VIEW_IDS})  # all pages in the sidebar, demo included
            for key, (label, kw) in nav.items():
                self.assertTrue(kw["icon"].startswith(":material/"), key)
                self.assertEqual(kw["type"], "primary" if key == f"nav-{view}" else "secondary", (view, key))
            self.assertEqual(self.st.session_state["view"], view)
        # a nav click only stores the view; the next run shows it
        from components import sidebar
        sidebar._go("alerts")
        self.assertEqual(self.st.session_state["view"], "alerts")
        self.assertEqual(self.st.query_params["view"], "alerts")

    def test_demo_page_hidden_outside_demo_mode(self):
        self.rt.update_settings(data_source="wokwi", wokwi_transport="paste")
        time.sleep(0.3)
        page = self.run_app("demo")  # asking for it anyway falls back to the overview
        self.assertEqual(self.st.session_state["view"], "overview")
        self.assertIn("Remaining gas", page)
        keys = [kw.get("key") for _, kw in self.st.buttons]
        self.assertNotIn("nav-demo", keys)
        self.assertIn("nav-settings", keys)

    def test_view_restored_from_url(self):
        self.st.query_params["view"] = "consumption"
        self.st.session_state.pop("view", None)
        self.run_app()
        self.assertEqual(self.st.session_state["view"], "consumption")
        self.assertEqual([k for k, _ in self.st.charts], ["chart_consumption"])
        self.st.session_state.pop("view", None)
        self.st.query_params["view"] = "nonsense"
        self.run_app()
        self.assertEqual(self.st.session_state["view"], "overview")

    def test_overview_alert_strip_and_layout_css(self):
        self.rt.update_settings(demo_interval_s=0.2, store_interval_s=1)
        time.sleep(0.8)
        from components import demo_panel
        demo_panel._jump(self.rt, 5.0)
        time.sleep(2.0)
        page = self.run_app("overview")
        self.assertIn("gg-alertstrip", page)
        self.assertIn("ACTIVE ALERT", page)
        self.assertNotIn("gg-alert-title", page)  # full printouts belong to the Alerts page
        self.run_app("alerts")
        self.assertIn("gg-alert-title", "\n".join(self.st.html_out))
        keys = [kw.get("key") for _, kw in self.st.buttons]
        self.assertIn("btn_theme_light", keys)
        self.assertIn("btn_theme_dark", keys)
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        hidden = css[:css.index("{", css.index("[data-testid=\"stToolbar\"]"))]
        self.assertNotIn("stSidebar", hidden)  # the sidebar must not be in the display:none list
        for needle in ("100vh", "gg_nav", "st-key-nav-", "@media (max-width: 768px)"):
            self.assertIn(needle, css)

    def test_wokwi_paste_end_to_end(self):
        self.rt.update_settings(data_source="wokwi", wokwi_transport="paste")
        time.sleep(0.6)
        demo_rows_before = self.rt.db.count("demo")  # the runtime starts in demo mode and seeds history
        from components import settings_panel
        self.st.session_state["paste_text"] = "\n".join(
            f"Total Weight: {20 - i * 0.05:.2f} kg | Gas Remaining: 5.00 kg | Level: 35.21%" for i in range(30)
        ) + "\nsome junk line"
        settings_panel._import_paste(self.rt)
        self.assertEqual(self.st.session_state["paste_result"][0], "ok")
        self.assertIn("Imported 30", self.st.session_state["paste_result"][1])
        time.sleep(2.0)
        self.assertEqual(self.rt.db.count("wokwi"), 30)
        self.assertEqual(self.rt.db.count("demo"), demo_rows_before)  # Wokwi data never lands in demo
        page = self.run_app("overview")
        self.assert_well_formed()
        self.assertIn("WOKWI", page)
        self.assertIn("IMPORTED", page)

    def test_demo_buttons_drive_the_alerts(self):
        self.rt.update_settings(demo_interval_s=0.2, store_interval_s=1)
        time.sleep(0.8)
        from components import demo_panel
        demo_panel._jump(self.rt, 5.0)
        for _ in range(40):
            time.sleep(0.25)
            if self.rt.manager.source.state()["target_weight"] is None:
                break
        time.sleep(1.2)
        page = self.run_app("alerts")
        self.assertIn("Critical gas level", page)
        self.assertIn("CRITICAL", page)
        demo_panel._jump(self.rt, 60.0)
        time.sleep(1.5)  # let the new level be stored before the next change
        demo_panel._spike(self.rt, -2.0)
        time.sleep(2.2)
        page = self.run_app("alerts")
        self.assertIn("Abnormal weight change", page)
        demo_panel._set_scenario  # exists
        self.st.session_state["demo_scenario"] = "sensor_fault"
        demo_panel._set_scenario(self.rt)
        time.sleep(1.5)
        page = self.run_app("alerts")
        self.assertIn("Sensor fault", page)
        self.assert_well_formed()

    def test_calibration_helpers(self):
        from components import settings_panel
        from data_source import Reading
        self.rt.update_settings(data_source="hardware")
        self.rt.db.insert(Reading("2026-11-21T10:00:00", 5.0, "arduino"))
        self.st.session_state["known_weight"] = 10.0
        settings_panel._calibrate_factor(self.rt)
        self.assertAlmostEqual(self.rt.settings.calibration_factor, 2.0)
        settings_panel._tare(self.rt)
        self.assertAlmostEqual(self.rt.settings.tare_offset_kg, -10.0)
        self.assertEqual(self.st.session_state["calib_result"][0], "ok")

    def test_clear_data_only_touches_current_mode(self):
        from components import settings_panel
        from data_source import Reading
        self.rt.update_settings(data_source="wokwi", wokwi_transport="paste")
        self.rt.db.insert(Reading("2026-11-21T10:00:00", 20.0, "wokwi"))
        before_demo = self.rt.db.count("demo")
        settings_panel._clear_data(self.rt)
        self.assertEqual(self.rt.db.count("wokwi"), 0)
        self.assertEqual(self.rt.db.count("demo"), before_demo)


def config_label(mode):
    import config
    return config.MODES[mode]["label"]


if __name__ == "__main__":
    unittest.main()
