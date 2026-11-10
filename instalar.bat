@echo off
chcp 65001 >nul
title HORIZONTE - instalação
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python não encontrado. Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/
  echo e marque a opção "Add python.exe to PATH" na instalação.
  pause
  exit /b 1
)
%PY% --version
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Falha ao instalar as dependências. Confira a internet e rode de novo.
  pause
  exit /b 1
)
if not exist ".env" copy ".env.example" ".env" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atalhos.ps1" -Modo criar
echo.
echo Instalação concluída.
echo - Agora existe o ícone HORIZONTE na área de trabalho e no menu Iniciar.
echo - Clique nele: o HORIZONTE fica na bandeja (perto do relógio) e abre o painel.
echo - Para ligar sozinho com o Windows: instalar_inicio_automatico.bat
echo - Para fixar na barra de tarefas: botão direito no ícone, "Mostrar mais opções", "Fixar na barra de tarefas".
pause
