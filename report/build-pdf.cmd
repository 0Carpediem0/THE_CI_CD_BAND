@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-pdf.ps1"
if errorlevel 1 pause
