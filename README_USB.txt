VIS WORKFLOW BENCHMARK v0.2 - USB PORTABLE BUILD
================================================

PURPOSE
Controlled, pure-task benchmarking for Vectorworks workflows.
Designed for manual/existing vs scripted/plugin comparisons.

RUNNING FROM USB
1. Copy the complete "VIS Workflow Benchmark" folder to a USB stick.
2. Double-click "VIS Workflow Benchmark.exe".
3. Enter the task/method details.
4. Use the hotkeys below while Vectorworks is active.

HOTKEYS
F6  Start benchmark
F7  Mark one meaningful workflow ACTION
F8  Mark one genuine DECISION / judgement point
F9  Start/end SOFTWARE WAIT
F12 Finish benchmark, save data and generate reports

AUTOMATIC METRICS
- Total task time
- Active working time
- Left/right/middle mouse clicks
- Keystroke count (not the actual keys)
- Scroll events
- Raw input event count
- Mouse travel in pixels
- Inactive/assessment time (>3 seconds without input)
- Ctrl+Z undo/rework count

EXPLICIT METRICS
- Actions: F7
- Decisions: F8
- Software wait: F9 to bracket a Vectorworks processing period

REPORT OUTPUTS
The Results folder sits beside the EXE and contains:
- VIS_Workflow_Benchmark_Data.csv (Power BI-compatible master dataset)
- One JSON summary per run
- A4 technical benchmark PDF
- A3 landscape presentation PDF
- Supporting 3D-style time-composition pie charts in paired reports

PAIRING
Use the same Pair ID for the manual/existing and automated/plugin runs.
The second completed run will create a paired comparison report.

PRIVACY / SCOPE
This is a workflow benchmark, not employee-monitoring software.
It does not save screen content, documents, filenames or actual typed characters.
Only event counts and timings are stored while a benchmark is running.

WINDOWS SECURITY NOTE
Because this is a newly self-built unsigned EXE, Windows SmartScreen or company
endpoint security may warn about it. If company IT policy blocks unsigned portable
executables, ask IT to approve/sign the EXE rather than bypassing company controls.
