@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-HLK.ps1" %*
if errorlevel 1 pause
