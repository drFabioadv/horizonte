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
if %errorlevel%==3 goto fim
if %errorlevel%==4 goto erro
echo O HORIZONTE parou. Reiniciando em 15 segundos... (feche esta janela para encerrar)
timeout /t 15 /nobreak >nul
goto loop
:erro
pause
exit /b 1
:fim
timeout /t 8 >nul
exit /b 0
