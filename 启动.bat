@echo off
rem ===========================================================================
rem  RPG Maker All-in-one Tool -- Windows launcher (double-click me)
rem
rem  Requirement 8-1: clean Python (stdlib only) + double-click -> UI opens.
rem
rem  This file is intentionally ASCII-only and logic-free: cmd.exe mangles
rem  multi-byte text in .bat files (measured: even with chcp 65001, a UTF-8
rem  batch file loses the FIRST BYTE of every non-ASCII line). All
rem  user-facing messages -- in Chinese -- live in run.py (plain UTF-8).
rem
rem  Interpreter preference: "python" on PATH first, then the "py" launcher.
rem  Why that order: "py -3" picks the NEWEST installed version, which may be
rem  a pre-release or an environment this project was never validated on,
rem  while "python" is exactly what the documented commands
rem  (python app.py / python tests/run_all.py) use. run.py re-checks the
rem  version and prints a readable message either way.
rem ===========================================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul && (python run.py %* & goto :done)
where py >nul 2>nul && (py -3 run.py %* & goto :done)

echo.
echo [ERROR] Python not found on PATH.
echo         This tool needs Python 3.8+ (standard library only).
echo         Install from https://www.python.org/downloads/ and tick
echo         "Add python.exe to PATH", then double-click this file again.
echo.
pause
exit /b 1

:done
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo [ERROR] Exit code %CODE%. See the messages above.
    echo         Port already in use? Try:  launcher.bat --port 0
    echo.
    pause
)
endlocal
