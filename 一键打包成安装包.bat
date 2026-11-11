@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
title DingXiangJing Toolbox - Build Installer

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

python "%~dp0build_installer.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo  ==================================================
    echo   BUILD OK  -  installer is ready.
    echo  ==================================================
) else (
    echo  ==================================================
    echo   BUILD FAILED  ^(exit code %RC%^)
    echo   See the messages above, then run again.
    echo  ==================================================
)
echo.
pause
exit /b %RC%
