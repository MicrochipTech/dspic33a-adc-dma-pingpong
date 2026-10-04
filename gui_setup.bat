@echo off
rem ---------------------------------------------------------------------
rem  gui_setup.bat - one-time set-up for tools\adc_gui.py and the other
rem  host tools.
rem
rem  Creates a private Python environment in tools\.venv and installs what
rem  they need into it: requirements-gui.txt (nicegui,
rem  pyserial, numpy) and requirements-board.txt (pyserial, numpy,
rem  matplotlib - matplotlib is only for eval_chain.py --png). Nothing is installed into the system
rem  Python. Run it again after a git pull that changed either requirements
rem  file; it only adds what is missing.
rem
rem  Needs: Python 3.10 or newer on the PATH (python --version), internet
rem  access for pip. Afterwards start the GUI with adc_gui.bat.
rem ---------------------------------------------------------------------
setlocal
rem  lives in the repository root; the environment and the tools are in tools\
cd /d "%~dp0tools"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found on the PATH. Install Python 3.10+ from python.org
  echo and tick "Add python.exe to PATH", then run this again.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment in %CD%\.venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo Creating the virtual environment failed.
    exit /b 1
  )
)

echo Installing / updating the dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements-gui.txt -r requirements-board.txt
if errorlevel 1 (
  echo.
  echo pip failed. No internet, or a proxy in the way? Set HTTPS_PROXY and try again.
  exit /b 1
)

echo.
echo Checking the GUI with its built-in self-test ...
".venv\Scripts\python.exe" adc_gui.py --selftest
if errorlevel 1 (
  echo The GUI self-test FAILED - see the messages above.
  exit /b 1
)

echo.
echo Done. Start the GUI with:
echo    adc_gui.bat --fake            (no board, synthetic signal)
echo    adc_gui.bat --port COM7       (the board's console port)
endlocal
