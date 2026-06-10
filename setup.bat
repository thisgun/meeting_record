@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "PS_ARGS="

:parse_args
if "%~1"=="" goto run_setup

if /I "%~1"=="--skip-models" (
    set "PS_ARGS=!PS_ARGS! -SkipModels"
    shift
    goto parse_args
)
if /I "%~1"=="--skip-doctor" (
    set "PS_ARGS=!PS_ARGS! -SkipDoctor"
    shift
    goto parse_args
)
if /I "%~1"=="--force" (
    set "PS_ARGS=!PS_ARGS! -Force"
    shift
    goto parse_args
)
if /I "%~1"=="--no-winget" (
    set "PS_ARGS=!PS_ARGS! -NoWinget"
    shift
    goto parse_args
)
if /I "%~1"=="--help" (
    set "PS_ARGS=!PS_ARGS! -Help"
    shift
    goto parse_args
)
if /I "%~1"=="-h" (
    set "PS_ARGS=!PS_ARGS! -Help"
    shift
    goto parse_args
)

echo Unknown option: %~1
echo.
echo Usage:
echo   setup.bat
echo   setup.bat --skip-models
echo   setup.bat --skip-doctor
echo   setup.bat --no-winget
echo   setup.bat --force
echo   setup.bat --help
exit /b 2

:run_setup
where powershell >nul 2>nul
if errorlevel 1 (
    echo Windows PowerShell was not found.
    echo Please run scripts\setup_windows.ps1 manually in PowerShell.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1" !PS_ARGS!
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo setup.bat completed.
) else (
    echo setup.bat failed with exit code %EXITCODE%.
)
echo.
pause
exit /b %EXITCODE%
