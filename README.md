# Power Supply Test Automation

[![tests](https://github.com/basel19982323-ux/power-supply-test-automation/actions/workflows/tests.yml/badge.svg)](https://github.com/basel19982323-ux/power-supply-test-automation/actions/workflows/tests.yml)

CI runs with simulated instruments only.

**Dynamic Load Test** is a Windows desktop application that automates electrical verification tests on
power supplies (AC-DC adapters, USB-C PD chargers, flyback converters). It controls the bench
instruments over SCPI/VISA, runs the test matrix hands-off, judges every point PASS/FAIL against
limits, and writes Excel and PowerPoint reports.

It was built for and used on a real lab bench. It automates the steps that are otherwise done by hand for
every test point: setting the AC input, stepping the load, adjusting the oscilloscope, reading the values and
copying them into a report.

**Author:** Basel Haijar · Electrical & Electronics Engineer · [LinkedIn](https://www.linkedin.com/in/basel-haijar)

## Engineering highlights

- **Instrument control over SCPI/VISA** for an ITECH AC source, an ITECH electronic load and a
  Yokogawa DLM oscilloscope (plus a POWER-Z USB-C PD decoy). Each driver keeps its commands in one
  table, so adapting to another model or firmware is a one-line change.
- **Three built-in tests:**
  - *Dynamic output response* (USB-C PD): load-transient sweep across PD profiles and AC input
    conditions; reads Vmax/Vmin and captures a waveform per point.
  - *V<sub>DS</sub> max at AC turn-off* (flyback primary MOSFET): cuts the AC input and single-shot
    captures the drain turn-off transient.
  - *V<sub>DS</sub> at OVP* (feedback break): triggers on the output rising and captures the peak
    drain voltage when over-voltage protection trips.
- **Automatic oscilloscope ranging**: measures the steady-state value first, sets the vertical scale,
  captures with peak detect and retries if the capture clips.
- **PASS/FAIL against derated limits**: the MOSFET V<sub>DS</sub> rating can be typed in or
  extracted from the component's datasheet PDF, then derated by a set margin.
- **Safety behaviour**: AC output off between conditions, load input off after each point, and an
  abort if a reading is far out of range (for example a bad probe). Before the AC is cut or the
  feedback is broken, the steady V<sub>DS</sub> is checked: impossible values are ERROR, and a
  value already above the limit is FAIL with no test event and the run stopped. The
  "1.5 × FET rating" top of the probe check is a provisional measurement check, not a safe voltage.
- **Pluggable test framework**: a new test type is one class; the GUI, runner, sequencing and
  reporting pick it up automatically.
- **Testable without hardware**: a simulation mode, plus a fake bench that speaks SCPI over TCP so the
  real drivers can be exercised. 23 automated tests (pytest).

**Tech:** Python · PySide6 (Qt) · PyVISA / SCPI · pytest · openpyxl · python-pptx · PyInstaller

## Screenshots

All screenshots are from **Simulation mode** (no hardware connected), so the values are simulated.

**VDS max at AC turn-off**: single-shot capture with the wide view (bulk-capacitor discharge) and the
zoomed turn-off detail, judged against the derated MOSFET rating:

![VDS turn-off run](docs/screenshots/run_vds_turnoff.png)

**Dynamic output response**: 16-point matrix (4 USB-C PD profiles × 4 AC input conditions) with the
latest waveform:

![Dynamic output response run](docs/screenshots/run_dynamic_output.png)

**Setup**: AC conditions, PD profiles and transient settings are edited in tables and saved as YAML:

![Setup tab](docs/screenshots/setup.png)

**Report**: results with limits, exported to Excel and PowerPoint:

![Report tab](docs/screenshots/report.png)

---

## Overview of the built-in tests

A Windows desktop application for **bench instrument test automation**. Built-in tests:

- **Dynamic Output Response** (USB-C PD): ITECH AC source + ITECH e-load + Yokogawa
  scope + POWER-Z. Sweeps PD output profiles × AC input conditions, reads Vmax/Vmin,
  captures a screenshot per point, PASS/FAILs against limits.
- **VDS Max — AC Turn-off** (flyback primary MOSFET): with the DUT running, cuts the AC
  input (AC source output OFF), single-shot captures the drain turn-off transient, and
  reads peak V_DS. The scope **auto-ranges** (measures steady-state V_DS to set the
  vertical scale, peak-detect capture, retry if the capture clips). PASS/FAIL vs. the FET
  V_DS rating × a derating margin — typed in, or extracted from an uploaded datasheet PDF.
- **VDS at OVP (feedback break)** (flyback primary MOSFET): the e-load holds a static load
  on the output; the app arms a single-shot triggered on **CH2 (output) rising** and
  prompts you to open the optocoupler switch (break the feedback loop). When the output
  jerks up to OVP it captures peak V_DS (CH1). Same auto-range/zoom/pass-fail as Turn-off,
  plus records the OVP output level.

Tests run **individually** (Test → Run) or **in succession** via the **Sequence** tab.
The core is a **pluggable test framework** — new test types slot in without touching the
GUI (see *Adding a test type* below).

---

## Quick start

```bat
setup.bat      :: one-time: create .venv and install dependencies
run.bat        :: launch the app
```

Requires Python 3.10+ on PATH. On first launch the app opens in **Simulation
mode**, so you can click through the entire workflow — run, live results,
reports — with **no hardware connected**.

Headless / CI smoke test (no GUI):

```bat
.venv\Scripts\python cli.py --simulate
.venv\Scripts\python -m pytest
```

---

## The workflow (six tabs)

1. **Test** — pick the test type and name the DUT.
2. **Instruments** — toggle **Simulation mode**, or enter VISA addresses for the
   AC source, e-load, and scope. **Scan** lists connected instruments; **Test**
   confirms each `*IDN?`. Choose the POWER-Z mode (manual/gui).
3. **Setup** — edit AC conditions, PD profiles, transient settings, and limits in
   tables/fields. **Save/Load** named configs (YAML).
4. **Run** — **Start**/**Abort**, a live progress table with PASS/FAIL coloring,
   running counts, and the latest waveform. In manual POWER-Z mode a dialog asks
   you to set the decoy once per output voltage.
5. **Report** — generate Excel + PowerPoint (built-in layout or your company
   template) and open the output folder.
6. **Sequence** — assemble an ordered suite of tests (each a test type + saved config),
   **Run all** in succession with per-step PASS/FAIL, then a combined report. Each step
   also writes its own timestamped run folder under `output/sequences/SEQ_<timestamp>/`.

Every run is saved to its own timestamped folder under `output/` (results never
overwrite each other):

```
output/<DUT>_<YYYYMMDD-HHMMSS>/
    results.csv
    screenshots/*.png
    <DUT>_report.xlsx   <DUT>_report.pptx   (after you generate them)
```

---

## Real hardware

1. Install the VISA backend (only needed for live runs):
   ```bat
   .venv\Scripts\python -m pip install pyvisa-py pyusb psutil zeroconf
   ```
2. Connect the AC source, e-load, and scope (LAN recommended; USB works). On the
   Yokogawa enable the remote interface (Utility → Remote Ctrl → Network →
   VXI-11 ON for LAN).
3. In the app: **Instruments** → uncheck Simulation → **Scan** → assign each
   address → **Test** each → **Setup** your matrix → **Run**.

**Honest first-session expectations**: the
drivers use the standard ITECH and Yokogawa command sets, but exact SCPI syntax
varies by model/firmware. Each driver prints `*IDN?` on connect and keeps all
commands in one `CMDS` dict at the top of its file — if a command errors, check
that model's programming manual and fix one line. Plan ~1–2 hours of first-run
debugging with instruments live; after that a full 16-point matrix runs in
minutes, hands-off. Safety behaviors are built in: AC output off between
conditions, load input off after each point, and a sanity-abort if a reading is
wildly out of range (bad probe).

**Before any real-hardware run: confirm the probes by hand.** The engineer must
check the probe type (for example a high-voltage differential probe on the
MOSFET drain) and that the probe attenuation set in the app (Setup → "Probe
attenuation"; for OVP also "Output probe atten." on CH2) matches the probe
that is really connected. The app can't
detect every wrong setting. Its probe check only rejects readings that are not
believable:

| Wrong probe setting | Detected by the app? |
|---|---|
| Probe disconnected (about 0 V) | Yes: ERROR `PROBE_CHECK` |
| Attenuation 10× too low (reads 10× too low) | Yes, for a normal flyback: ERROR `PROBE_CHECK` |
| Attenuation 10× too high (reads 10× too high), 650 V FET | Yes: ERROR `PROBE_CHECK`, run stopped |
| 10× too high with a very high-voltage FET at low line | Not by the probe check; the reading is above the limit, so FAIL and the run stops (never PASS) |
| **Small errors, for example 2× too low** | **No.** The reading looks normal and **could PASS a bad DUT** |

The "1.5 × FET rating" top of the probe check is a provisional measurement
check, not a safe operating voltage. These thresholds were tested in
simulation and against the fake bench only, not yet on real instruments.

---

## Testing without hardware

Two levels:

- **Simulation mode** (in-app toggle) — replaces the drivers with fakes. Fast, no
  setup; exercises the UI, config, sequencing, and reports, but sends no SCPI.
- **Fake bench** (`tools/fake_bench.py`) — a virtual AC source + e-load + scope that
  speaks SCPI over TCP sockets, so the app's **real** drivers run against it (real
  PyVISA, SCPI, binary screenshot transfer, trigger polling). Needs `pyvisa-py`.

  ```bat
  python tools\fake_bench.py      :: prints TCPIP0::127.0.0.1::5025/5026/5027::SOCKET
  ```
  Then in the app: **Instruments tab → Simulation OFF**, enter those addresses (or on
  the Setup tab load `configs/fake_bench_vds.yaml`), and run. Headless equivalent:
  ```bat
  python cli.py --test vds_turnoff --config configs\fake_bench_vds.yaml
  ```
  The VDS test is fully realistic here (cutting AC completes the scope's single-shot,
  auto-range + retry, real waveform PNGs). **Caveat:** a self-consistent fake validates
  the *plumbing*, not whether the SCPI strings match your exact DLM/ITECH models — only
  a real instrument proves that. Select a different VISA backend with the
  `DLT_VISA_BACKEND` env var (default `@py`; e.g. `@sim` for pyvisa-sim).

## Reports & the company template

Without a template, the app writes a clean built-in layout. When you have the
company format, drop the file(s) into `reporting/templates/` and, on the Report
tab, tick **Use company template**:

- **Excel** — your `.xlsx` is filled per a small `mapping.yaml` (copy
  `reporting/mapping.example.yaml`): summary cells + where the results table
  starts. The data pipeline is identical to the default.
- **PowerPoint** — your `.pptx` is used as the theme/branding base for the
  generated deck. Per-placeholder mapping can be added once the real template's
  layout is known.

---

## Adding a test type

The GUI, runner, persistence, and reporting are all generic. To add a test:

1. Create `testtypes/<your_test>.py` with a `TestType` subclass implementing
   `default_config()`, `config_schema()`, `plan()`, and `execute_point()` (see
   `testtypes/dynamic_output_response.py` as the reference).
2. Register it in `testtypes/__init__.py` (`REGISTRY`).

That's it — it appears in the Test dropdown, gets a full Setup editor from its
`config_schema()`, runs with live monitoring, and reports automatically.

---

## Build a standalone .exe

```bat
build.bat      :: -> dist\DynamicLoadTest\DynamicLoadTest.exe
```

Distribute the whole `dist\DynamicLoadTest\` folder to a bench PC (no Python
install needed). For live hardware on that PC, the VISA backend must be bundled
or installed alongside.

---

## Project layout

```
main.py            app entry point            cli.py     headless engine runner
core/              engine: runner, config, results, sequence, VISA scan,
                   datasheet (VDS-rating extractor), TestType base
  instruments/     drivers (real) + simulator + factory
testtypes/         pluggable tests: dynamic_output_response, vds_turnoff
reporting/         Excel + PPTX builders, template-fill, sequence summary, templates/
ui/                PySide6 tabs + threaded run/sequence workers
configs/           saved test configs (YAML)
tests/             pytest suite (engine, config, reporting, vds, datasheet, sequence)
```

---

## License

MIT License. See [LICENSE](LICENSE).
