@echo off
chcp 65001 >nul
title HORIZONTE
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Rode instalar.bat primeiro.
  pause
  exit /b 1
)
:loop
".venv\Scripts\python.exe" -m horizonte %*
echo O HORIZONTE parou. Reiniciando em 15 segundos... (feche esta janela para encerrar)
timeout /t 15 /nobreak >nul
goto loop
