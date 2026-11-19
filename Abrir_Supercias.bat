@echo off
cd /d "%~dp0"
py "%~dp0app_supercias.py"
if errorlevel 1 pause