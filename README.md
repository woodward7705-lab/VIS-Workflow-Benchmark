# VIS Workflow Benchmark

Portable Windows workflow benchmarking tool for controlled Vectorworks task testing.

## Metrics

Tracks total task time, active time, inactivity/assessment time, software wait time, mouse clicks, keystrokes, mouse travel, action markers, decision markers, undo/rework and related task metadata. Results are saved in Power BI-compatible CSV/JSON files and can generate A4/A3 PDF reports, including 3D-style time-composition charts.

## Hotkeys

- **F6** — Start test
- **F7** — Action +1
- **F8** — Decision +1
- **F9** — Start/end Software Wait
- **F12** — Finish test and generate outputs

The recorder counts keystrokes but does **not** store the actual keys typed and does not capture screen images.

## Build the Windows EXE with GitHub Actions

1. Upload all files and folders in this repository package to the root of the GitHub repository.
2. Open the repository **Actions** tab.
3. Select **Build Windows EXE**.
4. Click **Run workflow** if a build has not already started automatically.
5. When the build completes, open the successful run and download the artifact named **VIS-Workflow-Benchmark-Windows**.
6. Unzip the artifact. Copy the **VIS Workflow Benchmark** folder to a USB stick.
7. Run **VIS Workflow Benchmark.exe**. Python is not required on the PC running the finished EXE.

The application writes its `Results` folder beside the EXE, so it remains portable on USB storage.
