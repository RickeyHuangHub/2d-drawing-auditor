@echo off
chcp 65001 >nul
title 2D图纸审核高手

echo ========================================
echo   2D图纸审核高手 - 启动脚本
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM ========== AI 配置 ==========
REM 【重要安全提醒】API Key 不得硬编码在本文件中，也绝不能提交到 GitHub！
REM 本文件不含任何真实 Key，请通过"用户环境变量"配置（仅当前用户可见，不进入项目仓库）。
REM
REM 一次性设置方法（PowerShell，以管理员或普通用户身份运行均可）：
REM   setx AI_API_KEY  "你的Agnes API Key"
REM   setx AI_BASE_URL "https://apihub.agnes-ai.cn/v1"
REM   setx AI_MODEL    "agnes-2.5-flash"
REM 设置后需关闭并重新打开命令行窗口才会生效。
REM
REM 以下两项为非敏感默认值，可直接写在本文件中：
if not defined AI_BASE_URL set "AI_BASE_URL=https://apihub.agnes-ai.cn/v1"
if not defined AI_MODEL set "AI_MODEL=agnes-2.5-flash"
REM ==========================================

REM 优先使用项目内虚拟环境（.venv），否则回退到系统 Python
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
    echo [信息] 使用项目虚拟环境 .venv
)

REM 检查 Python
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM 检查依赖
echo [1/3] 检查依赖...
%PY% -c "import fastapi, uvicorn, fitz, PIL, httpx" >nul 2>&1
if errorlevel 1 (
    echo [2/3] 安装依赖...
    %PY% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络连接
        echo.
        pause
        exit /b 1
    )
) else (
    echo [2/3] 依赖已就绪
)

REM 检查 AI API Key（不阻止启动，仅提示）
echo [3/3] 检查配置...
if "%AI_API_KEY%"=="" (
    echo.
    echo [提示] 未检测到 AI_API_KEY 环境变量，将以演示模式启动
    echo        AI审核返回模拟数据，可完整测试流程和界面
    echo.
    echo        如需真实 AI 审核，请在 PowerShell 中一次性设置：
    echo          setx AI_API_KEY  "你的Agnes API Key"
    echo          setx AI_BASE_URL "https://apihub.agnes-ai.cn/v1"
    echo          setx AI_MODEL    "agnes-2.5-flash"
    echo        设置后重新打开本脚本即可。
    echo.
)

REM 读取端口配置（端口配置.txt 里写一个数字即可换端口，避免与其它程序冲突）
set "PORT=8080"
if exist "%~dp0端口配置.txt" (
    set /p PORT=<"%~dp0端口配置.txt"
)
if "%PORT%"=="" set "PORT=8080"
echo.
echo 当前访问地址: http://127.0.0.1:%PORT%
echo 如需更换端口，请编辑"端口配置.txt"后重新启动
echo.

echo 启动服务...
echo 浏览器将自动打开应用页面
echo 按 Ctrl+C 停止服务
echo.

REM 启动服务（出错时暂停显示错误）
%PY% "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo [错误] 服务启动失败，错误代码: %errorlevel%
    echo.
    pause
)
