@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atalhos.ps1" -Modo criar
echo.
echo Para deixar o HORIZONTE na barra de tarefas: clique com o botão direito no ícone
echo da área de trabalho, "Mostrar mais opções" e "Fixar na barra de tarefas".
pause
