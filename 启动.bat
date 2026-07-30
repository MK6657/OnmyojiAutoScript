@echo off
chcp 65001 >nul
title OAS Control Center
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-center\start.ps1" -Menu %*
pause
