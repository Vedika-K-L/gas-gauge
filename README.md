# GAS GAUGE: Smart LPG Monitoring Dashboard

A Streamlit dashboard for the Arduino + HX711 + load cell LPG monitor. It runs in three modes, and each mode's data is stored and displayed separately:

| Mode | What it reads | Needs hardware? |
|------|---------------|-----------------|
| **DEMO** | Built-in generator (a week of history plus live drift) | No |
| **WOKWI SIMULATION** | Your Wokwi sketch's serial output | No |
| **PHYSICAL HARDWARE** | Arduino Uno over USB serial (PySerial) | Only when you have it |

Every reading is stored with its source, and every chart, metric and alert reads only the active source. Demo data can never appear as sensor data.

## Run it in VS Code

1. Open this folder in VS Code (`File > Open Folder`).
2. Open a terminal (`Ctrl+` backtick) and run:

   ```bash
   python -m venv .venv
   # Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
   pip install -r requirements.txt
   streamlit run app.py
   ```

3. The dashboard opens at <http://localhost:8501> and starts in **Demo mode**.

Switch mode or edit any setting from the **Settings** panel in the header. Settings are saved to `data/settings.json` and readings to `data/gas_history.db`.

## Connecting your Wokwi simulation

Wokwi runs in its own simulator. It does **not** create a COM port on your computer, so this app offers three bridges (Settings > Data source > Wokwi):

1. **Wokwi for VS Code serial bridge (live).** This is the only live option. The Wokwi VS Code extension can forward the simulated serial port over a local TCP port. Add this to your project's `wokwi.toml`:

   ```toml
   [wokwi]
   rfc2217ServerPort = 4000
   ```

   Start the simulation in VS Code, then choose *serial bridge* with URL `rfc2217://localhost:4000`. PySerial reads it like a normal port. The Wokwi docs show this setting in a MicroPython example; I could not test it against a live Wokwi project.
2. **Serial log file.** Point the app at a text file that something appends the serial output to. The app tails it.
3. **Paste.** If you simulate on wokwi.com in the browser, copy lines from the Serial Monitor and paste them in. They are imported with timestamps spaced 1 s apart, ending now. This is not live.

### What the sketch sends

```
Total Weight: 18.50 kg | Gas Remaining: 3.50 kg | Level: 24.65%
```

The parser reads this exact line (also tolerating `nan`/`inf`, extra spaces and CRLF). The dashboard recalculates remaining gas and percentage from the **weight** using its own Cylinder settings, so the numbers always follow the settings you see on screen.

## Things worth knowing about your sketch

* **No serial output on sensor failure.** When the HX711 isn't ready, the sketch only writes to the LCD. The dashboard detects this as *silence* and raises "Sensor disconnected" after the configured stale timeout (default 15 s).
* **Tare at startup.** `scale.tare()` runs once at boot, so readings are relative to whatever was on the platform then. With a real cylinder, power up with the platform empty, then place the cylinder (or remove the tare and calibrate properly).
* **Weight range vs. cylinder settings.** The sketch's example values are `emptyCylinderWeight = 15.0` and `gasCapacity = 14.2`, which are also the dashboard defaults. If your Wokwi load cell can't reach 15 kg, the level will read 0% and CRITICAL. Check the load cell's maximum in Wokwi and set *Empty cylinder weight* and *Capacity* in Settings to match (or change them in the sketch too).
* **Calibration.** The sketch uses `calibrationFactor = 1.0`, a placeholder. No real calibration value is built into this app. For hardware mode, Settings has a factor and offset, applied only to hardware readings, plus a helper that computes a factor from a known weight. Proper calibration is best done in the sketch with `scale.set_scale()`.

## Physical hardware (later)

Plug in the Uno, choose **Physical hardware**. Leave the port empty to auto-detect (the board is found by USB IDs; Uno clones with CH340/CP210x chips are included), or choose a port. Baud rate defaults to 9600, matching `Serial.begin(9600)`. Close the Arduino IDE Serial Monitor first, because only one program can hold the port.

## Alerts

Low gas (default 25%), critical gas (default 10%), sensor disconnected / sensor fault, abnormal weight change (default 1.5 kg within 10 minutes), refill or cylinder replacement detected (a rise of 5 kg or more by default), and connection errors. All thresholds are editable. The default Low and Critical cut-offs line up with the sketch's LED/LCD status (above 60% normal, above 25% medium, otherwise low).

## Project layout

```
app.py                  Streamlit entry point
config.py               Settings, palettes, constants
runtime.py              Shared settings + database + background reader
data_source.py          Standard Reading format, parser, source manager
wokwi_connector.py      Wokwi bridges (rfc2217 / log file / paste)
arduino_connector.py    PySerial hardware connector + port auto-detect
demo_generator.py       Demo source and 7-day history
data_manager.py         SQLite storage
analytics.py            Gas maths, consumption, days remaining
alerts.py               Alert rules
components/             Header, gauge, cards, charts, settings, demo controls
assets/styles.css       Theme and layout
tests/                  python -m unittest discover -s tests
```

After editing backend `.py` files, stop and restart `streamlit run app.py`. The background reader is created once per process.

## Tests

```bash
python -m unittest discover -s tests
```

The suite checks the parser against your sketch's exact line, the gas formulas (never negative, never above 100%), source separation, alerts, demo history, and the Wokwi log/paste bridges. The UI smoke tests run the full page against a stub of Streamlit and Plotly, so they check markup and logic, not live rendering in a browser.

---

## Premium UI layer (v1.1)

All five pieces live inside the one dashboard and read the same live readings as the original widgets.

| # | Piece | Where | Fed by |
|---|-------|-------|--------|
| 1 | Animated 3D LPG cylinder (4 views: Cylinder, Cutaway, Sensor Assembly, Exploded) | `frontend/src/components/ui/gas-gauge-3d.tsx`, wrapped by `components/gas_gauge_3d.py` | `gas.level_pct`, `remaining_kg`, `weight`, source mode, connection state |
| 2 | Live analytics: stat tiles + glow-line charts | `components/live_stats.py`, `components/charts.py` | stored history for the selected time range |
| 3 | Dot-matrix alert printouts and warning toasts | `components/notifications.py` + CSS | the alert engine (`alerts.py`) |
| 4 | Spotlight glow cards | `components/spotlight.py` + CSS | pointer position; tone follows warn/critical |
| 5 | Glassmorphism panels, ambient lighting | `assets/styles.css`, theme keys in `config.py` | theme |

Python backend, Arduino/Wokwi connectors, SQLite storage and settings are unchanged.

### Building the 3D viewer (one time)

Streamlit cannot import a React file directly, so the viewer is a Streamlit *custom component*: a small Vite app that Streamlit loads in an iframe.

```bash
cd frontend
npm install
npm run build        # writes frontend/dist
cd ..
streamlit run app.py
```

Until `frontend/dist` exists the dashboard shows a card with these commands and everything else works normally.
`npm run dev` opens a standalone preview with sliders (visual states only, never sensor data).

The viewer is display-only: it never talks to the Arduino and never sends values back to Python, so it does not trigger reruns. Gas level comes only from props.

### Verification status (please read)
- Python logic and the page markup are covered by the test suite (`python -I -m unittest discover -s tests`), which uses fake `streamlit`/`plotly` modules.
- The TSX passes an esbuild syntax check. It has **not** been type-checked against real Three.js, built with Vite, or run in a browser, and the CSS/Plotly/Streamlit rendering has not been seen in a real browser. It targets Three.js r180 APIs. Expect to fix small things on first build, and tell me what the compiler or console says.
- The spotlight needs the browser to allow the component iframe to reach the parent page (normal on `streamlit run`); otherwise cards just stay static.

## Deploying to Streamlit Community Cloud
1. Create a GitHub repo and push this folder's contents (the folder containing `app.py` must be the repo root).
2. On share.streamlit.io choose the repo, branch and `app.py`.
3. The 3D viewer needs `frontend/dist`. Either run `cd frontend && npm install && npm run build` locally and commit `dist`, or let the included GitHub Action (`.github/workflows/build-3d.yml`) build and commit it after you push (Actions tab, "Run workflow", or push any change under `frontend/`). Streamlit then redeploys.
4. Cloud runs demo mode only; Wokwi and Arduino need the app running on your own computer. The SQLite file lives on the server's disk and may reset on restart.
