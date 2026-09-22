@echo off
rem snowq - run the CLI straight from this checkout (Windows).
rem
rem Works with no install at all: finds a Python that has requests, puts src\
rem on the path, and hands over to "python -m snowq". Prefers a synced .venv,
rem so login and import-browser work once those extras are installed.
rem
rem   snowq.cmd doctor
rem   snowq.cmd -i acme import-cookie < cookie.txt
rem   snowq.cmd -i acme query incident -q "active=true" -n 5 -o table
rem
rem The sibling "snowq" script is the POSIX / Git Bash version.

setlocal EnableExtensions
pushd "%~dp0"

set "SESSIONS=%USERPROFILE%\.config\snowq\sessions"

rem ---- pick an interpreter that can actually import requests
set "PY="
if not exist ".venv\Scripts\python.exe" goto :try_path
".venv\Scripts\python.exe" -c "import requests" >nul 2>&1
if not errorlevel 1 set "PY=.venv\Scripts\python.exe"

:try_path
if defined PY goto :have_python
python -c "import requests" >nul 2>&1
if not errorlevel 1 set "PY=python"

:try_launcher
if defined PY goto :have_python
py -3 -c "import requests" >nul 2>&1
if not errorlevel 1 set "PY=py -3"

:have_python
if not defined PY goto :no_python

rem ---- src-layout: without this you get "No module named snowq"
if defined PYTHONPATH set "PYTHONPATH=src;%PYTHONPATH%"
if not defined PYTHONPATH set "PYTHONPATH=src"

if /i "%~1"=="doctor" goto :doctor

%PY% -m snowq %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

rem --------------------------------------------------------------- doctor
:doctor
%PY% -c "import sys; print('python      ' + (sys.executable or '?'))"
%PY% -c "import sys; print('version     %%d.%%d.%%d' %% sys.version_info[:3])"
echo PYTHONPATH  %PYTHONPATH%
echo.
call :check_module requests
call :check_module playwright
call :check_module browser_cookie3
echo.
%PY% -c "import snowq" >nul 2>&1
if errorlevel 1 goto :no_import
echo snowq imports cleanly.
echo.
if exist "%SESSIONS%\*.session.json" goto :list_sessions
echo No saved session yet. Get one with:
%PY% -c "import playwright" >nul 2>&1
if not errorlevel 1 goto :hint_login
echo   snowq.cmd -i ^<instance^> import-cookie ^< cookie.txt
echo   ^(login needs playwright, which is not installed here^)
goto :done

:hint_login
echo   snowq.cmd -i ^<instance^> login
goto :done

:list_sessions
echo saved sessions:
for %%F in ("%SESSIONS%\*.session.json") do call :strip_name "%%~nF"
goto :done

:no_import
echo snowq does NOT import - is src\snowq\ present?
popd
exit /b 1

:done
popd
exit /b 0

rem --------------------------------------------------------------- errors
:no_python
echo snowq: no Python with 'requests' installed. 1>&2
echo. 1>&2
echo   requests is the only hard dependency. Either: 1>&2
echo     uv sync --extra login            ^(if you can reach a package index^) 1>&2
echo     pip install requests             ^(or just this one package^) 1>&2
echo. 1>&2
echo   If uv says 'requests was not found in the package registry', it 1>&2
echo   reached no index at all. See docs\install.md. 1>&2
popd
exit /b 1

rem --------------------------------------------------------------- helpers
:check_module
%PY% -c "import %1" >nul 2>&1
if errorlevel 1 echo   no   %1
if not errorlevel 1 echo   yes  %1
goto :eof

:strip_name
rem %%~nF leaves "<host>.session"; drop that tail for the same output as ./snowq
set "NAME=%~1"
if "%NAME:~-8%"==".session" set "NAME=%NAME:~0,-8%"
echo   %NAME%
goto :eof
