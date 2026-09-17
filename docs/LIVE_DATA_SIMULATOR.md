# Live Data Simulator

## Purpose

`scripts/live_demo_replay.py` creates a controlled live replay for the LinePulse AI demo. It adds new `Usage_Log` and `Sensor_Readings` rows at a timed interval so the dashboard can score fresh signal values and show early-warning alerts for Class A assets.

This is a synthetic live replay for the hackathon demonstration. It is not a connection to plant equipment, an historian, a PLC, or a CMMS.

## Scenarios

Each replay step adds one new weekly observation for five Class A assets. The script changes actual sensor fields and leaves `ScenarioFlag` blank.

| Scenario | Signal changed |
|---|---|
| Overheating | Average and maximum temperature increase |
| Vibration increase | Average and maximum vibration increase |
| Excess current | Average and maximum current increase |
| Cycle-time drift | Cycle time increases |
| Pressure drop | Average pressure decreases |

The application scores the measurements and their trend. The script does not use `ScenarioFlag` as a shortcut.

## Run the replay

Use two PowerShell terminals. Start the dashboard first:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

In the second terminal, start the replay. The default mode writes to the original workbook and first creates a backup.

```powershell
.\.venv\Scripts\python.exe scripts\live_demo_replay.py start --steps 6 --interval 5
```

This produces six increasingly severe observations, five seconds apart. Refresh the browser after each step to load the changed workbook; the dashboard keys its service cache to the workbook modification time.

If Windows reports that the workbook is locked, close Excel and stop the dashboard, then rerun the replay. After the replay finishes, restart the dashboard and refresh the browser. Do not leave the workbook open in Excel while the simulator writes to it.

## Cleanup and restore

After the demo, run:

```powershell
.\.venv\Scripts\python.exe scripts\live_demo_replay.py cleanup
```

Cleanup restores `data/source/Synthetic_Dataset.xlsx` from `data/source/Synthetic_Dataset.live-demo-backup.xlsx`, then removes the backup and its replay manifest. If cleanup cannot find the backup, do not continue writing to the workbook; restore it from your own copy first.

## Optional disposable workbook mode

To keep the original workbook untouched, use:

```powershell
.\.venv\Scripts\python.exe scripts\live_demo_replay.py start --demo-copy --steps 6 --interval 5
```

This writes to `data/source/Synthetic_Dataset.live-demo.xlsx`. Start the dashboard with:

```powershell
$env:LINEPULSE_DATA_PATH = "$PWD\data\source\Synthetic_Dataset.live-demo.xlsx"
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

Run the same `cleanup` command afterward to remove the disposable workbook.

## Demo wording

Say: “This is a live replay of changing synthetic temperature, vibration, current, cycle-time, and pressure signals. LinePulse rescored the Class A assets as each new observation arrived. It is a hackathon simulator, not a live plant integration.”

Do not describe the replay as production telemetry, a real equipment connection, or validated failure prediction.
