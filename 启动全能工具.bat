@echo off
rem ---------------------------------------------------------------------------
rem RPG Maker 全能工具 —— 启动脚本（双击运行）
rem
rem 职责：找到可用的 Python，然后启动 app.py（唯一入口）。
rem 沿用原翻译工具 启动翻译工具.bat 的查找顺序：
rem   PATH 上的 python -> %LOCALAPPDATA% 下的常见安装位置 -> 自带运行时
rem 找不到时给出明确提示，不静默失败。
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN="

rem 1) PATH 上的 python
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_BIN=python"
if defined PYTHON_BIN goto :check_version

rem 2) 常见安装目录
for %%V in (313 312 311 310 39 38) do (
    if not defined PYTHON_BIN (
        if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PYTHON_BIN=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    )
)
if defined PYTHON_BIN goto :check_version

rem 3) 工具自带运行时（如存在）
if exist "%~dp0runtime\python\python.exe" set "PYTHON_BIN=%~dp0runtime\python\python.exe"
if defined PYTHON_BIN goto :check_version

echo [错误] 没有找到 Python。
echo.
echo 请先安装 Python 3.8 或更高版本：https://www.python.org/downloads/
echo 安装时务必勾选 "Add Python to PATH"，然后重新运行本脚本。
echo.
pause
exit /b 1

:check_version
rem 版本检查：本工具要求 3.8+（硬约束 §4.1）
"%PYTHON_BIN%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [错误] 找到的 Python 版本过低：请使用 Python 3.8 或更高版本。
    "%PYTHON_BIN%" --version
    echo.
    pause
    exit /b 1
)

rem 启动。默认自动打开浏览器；如不需要，把 --no-browser 加到下面这行。
"%PYTHON_BIN%" app.py %*
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [错误] 工具退出，代码 %EXITCODE%。上面的信息可用于排查。
    pause
)
endlocal & exit /b %EXITCODE%
