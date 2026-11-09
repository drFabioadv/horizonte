@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Startup')+'\HORIZONTE.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0iniciar_oculto.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.Description='HORIZONTE - central editorial'; $s.Save()"
if errorlevel 1 (
  echo Não foi possível criar o atalho de inicialização.
) else (
  echo Pronto: o HORIZONTE vai iniciar sozinho, sem janela, toda vez que você entrar no Windows.
  echo Painel: http://localhost:8787
)
pause
