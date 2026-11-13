@echo off
rem Start Pyomo Studio. Install first with: python -m pip install -r requirements.txt
cd /d "%~dp0"
python -m pyomo_studio %*
if errorlevel 1 pause
