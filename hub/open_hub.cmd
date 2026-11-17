@echo off
cd /d "%~dp0"
python hub_ui.py
if errorlevel 1 pause
