@echo off
REM ── HX Sentinel: one-click launcher ──────────────────────────────────────
REM   1. Flask API        -> http://localhost:5000  (calculations)
REM   2. Static dashboard -> http://localhost:8080  (UI)
REM   3. Opens the dashboard in the default browser
REM Each server runs in its own window; close that window to stop it.

set "ROOT=C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML"
set "PY=%ROOT%\venv\Scripts\python.exe"

echo Starting Flask API on http://localhost:5000 ...
start "HX Sentinel API (5000)" /D "%ROOT%" "%PY%" "%ROOT%\api.py"

echo Starting dashboard server on http://localhost:8080 ...
start "HX Sentinel Dashboard (8080)" /D "%ROOT%" "%PY%" -m http.server 8080

echo Waiting for servers to come up ...
timeout /t 3 /nobreak >nul

echo Opening dashboard in browser ...
start "" "http://localhost:8080/dashboard.html"

echo.
echo Both servers are now running, each in its own window.
echo Close those two windows to stop the servers.
echo (This window can be closed.)
pause
