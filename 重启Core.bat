@echo off
chcp 65001 >nul
title OAS Restart Core
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-center\start.ps1" -RestartCore %*
pause
