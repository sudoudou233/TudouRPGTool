@echo off
rem ===========================================================================
rem  RPG Maker All-in-one Tool -- Windows launcher (double-click me)
rem
rem  Requirement 8-1: clean Python (stdlib only) + double-click -> UI opens.
rem
rem  This file is intentionally ASCII-only: cmd.exe mangles multi-byte text in
rem  .bat files (measured: even with chcp 65001, a UTF-8 batch file loses the
rem  FIRST BYTE of every non-ASCII line). All user-facing messages -- in
rem  Chinese -- live in run.py (plain UTF-8).
rem
rem  WHY WE PROBE BY RUNNING, NOT BY "where"  (real bug report, exit 9009)
rem  -------------------------------------------------------------------
rem  A user double-clicked this file and got, with NOTHING printed above it:
rem
rem      [ERROR] Exit code 9009. See the messages above.
rem
rem  9009 is cmd's "command not found": the interpreter name resolved to
rem  something that could not be executed. "where python" DOES find something
rem  on a default Windows 10/11 -- a 0-byte Microsoft Store placeholder at
rem  %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe. So the old check
rem  ("where python exists? then run it") passed, the run failed with 9009,
rem  and run.py never started -- which is why there were no messages at all.
rem
rem  Two consequences, both fixed here:
rem    1. every candidate is now RUN (python -c "import sys"); a name that
rem       merely resolves no longer counts as "Python installed";
rem    2. store placeholders (path contains WindowsApps) are skipped, so a
rem       real Python reachable through the "py" launcher still gets used --
rem       the launcher now heals this case by itself instead of failing.
rem
rem  Interpreter order: "python" on PATH first, then the "py" launcher.
rem  Why that order: "py -3" picks the NEWEST installed version, which may be
rem  a pre-release or an environment this project was never validated on,
rem  while "python" is exactly what the documented commands
rem  (python app.py / python tests/run_all.py) use. run.py re-checks the
rem  version and prints a readable message either way.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "PYEXE="
set "PYARGS="
if not defined PYEXE call :try python
if not defined PYEXE call :try py -3
if not defined PYEXE call :try python3
if not defined PYEXE goto :nopython

rem  NOTE the "call": invoking a .bat from a .bat WITHOUT call hands control
rem  over for good -- the rest of this file never runs and the window closes
rem  with NO message at all. PATH entries named python.bat / python.cmd do
rem  exist in the wild (conda, pyenv-win and other shims install them), so
rem  this is not hypothetical: without call the launcher dies silently.
call "%PYEXE%" %PYARGS% run.py %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" goto :failed
goto :done

rem --------------------------------------------------------------- candidates
rem  :try <name> [args] -- for every path "where <name>" reports, probe it.
:try
set "_NAME=%~1"
set "_ARGS=%~2"
for /f "delims=" %%P in ('where %_NAME% 2^>nul') do (
    if not defined PYEXE call :probe "%%P" "%_ARGS%"
)
goto :eof

:probe
set "_P=%~1"
set "_A=%~2"
rem (a) skip the Microsoft Store placeholder -- running it pops the Store
rem     and/or fails with 9009, and it is NOT a usable Python.
echo "%_P%" | find /i "WindowsApps" >nul
if not errorlevel 1 goto :eof
rem (b) it must actually execute. "call" for the same reason as above.
call "%_P%" %_A% -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%_P%"
set "PYARGS=%_A%"
goto :eof

rem ------------------------------------------------------------------- errors
:failed
echo.
if "%CODE%"=="9009" goto :notfound
echo [ERROR] Exit code %CODE%. See the messages above.
echo.
echo         If a message above says the port is in use, start again with:
echo             %~nx0 --port 0
echo.
pause
endlocal & exit /b %CODE%

:notfound
echo [ERROR] Windows could not run the Python interpreter we found
echo         (exit code 9009 means "command not found").
echo         Tried: "%PYEXE%" %PYARGS%
echo.
echo         This almost always means the "python" on your PATH is the
echo         Microsoft Store shortcut, not a real Python. Either fix works:
echo           1) Install Python 3 from https://www.python.org/downloads/
echo              and TICK "Add python.exe to PATH"; or
echo           2) Settings ^> Apps ^> Advanced app settings ^>
echo              App execution aliases ^> turn OFF python.exe and python3.exe
echo.
echo         Note: a Python installed from the Store does work -- this only
echo         rejects the empty alias stub.
echo.
pause
endlocal & exit /b %CODE%

:nopython
echo.
echo [ERROR] Python not found on PATH.
echo         This tool needs Python 3.8+ (standard library only).
echo         Install from https://www.python.org/downloads/ and tick
echo         "Add python.exe to PATH", then double-click this file again.
echo.
echo         Already installed? Then the "python" on your PATH may be the
echo         Microsoft Store shortcut. See fix 2 in the notes at the top of
echo         this file, or run:  py -3 run.py
echo.
pause
endlocal & exit /b 1

:done
endlocal & exit /b 0
