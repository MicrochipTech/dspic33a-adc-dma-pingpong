@echo off
rem  filterdesign.bat - start the filter design GUI (tools\filterdesign\gui\app.py).
rem  Its dsPIC33 tab installs the designed filter into this firmware
rem  (src\core\user_filter.h, "sigproc user"), builds, flashes and opens the
rem  dsPIC33 GUI (adc_gui.py). Uses tools\.venv (gui_setup.bat) when it exists,
rem  else the python on the PATH (needs nicegui, numpy, scipy and a host gcc).
rem  Arguments go through: --port 8090, --no-browser, --light, --presets DIR
setlocal
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
cd /d "%~dp0filterdesign\gui"
"%PY%" app.py %*
endlocal
