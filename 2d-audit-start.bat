@echo off
title Drawing Audit Expert
cd /d "%~dp0"

echo Starting Drawing Audit Expert...
echo.

.venv\Scripts\python.exe main.py

echo.
echo ========================================
echo  Service stopped. Press any key to close.
echo ========================================
pause >nul