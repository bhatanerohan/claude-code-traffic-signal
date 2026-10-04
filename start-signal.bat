@echo off
rem Start the Claude Code traffic-signal overlay (no console window).
rem Prefers the py launcher; falls back to whatever pythonw is on PATH.
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0overlay.pyw" & exit /b)
start "" pythonw "%~dp0overlay.pyw"
