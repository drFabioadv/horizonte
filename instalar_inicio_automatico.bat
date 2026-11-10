@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atalhos.ps1" -Modo inicio
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HORIZONTE (antigo).lnk" 2>nul
pause
