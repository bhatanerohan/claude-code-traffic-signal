@echo off
rem Stop the traffic-signal overlay.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*overlay.pyw*' -and $_.Name -match '^pythonw?|^pyw' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
