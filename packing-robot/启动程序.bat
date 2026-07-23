@echo off
cd /d "%~dp0"
set QT_API=pyside6
python main.py
if errorlevel 1 pause
