@echo off
chcp 65001 >nul
title Drawing Audit Expert (LAN)
cd /d "%~dp0"

echo Starting Drawing Audit Expert...
echo LAN mode: 局域网内其他设备可通过下方地址访问
echo.

rem 自动获取本机局域网 IPv4 地址
set LANIP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
  if not defined LANIP set LANIP=%%a
)
set LANIP=%LANIP: =%
if "%LANIP%"=="" set LANIP=127.0.0.1

echo 本机局域网访问地址: http://%LANIP%:9808
> "LAN地址.txt" echo http://%LANIP%:9808
echo 地址已写入文件: LAN地址.txt
echo.

set HOST=0.0.0.0

.venv\Scripts\python.exe main.py

echo.
echo ========================================
echo  Service stopped. Press any key to close.
echo ========================================
pause >nul