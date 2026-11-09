@echo off
chcp 65001 >nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HORIZONTE.lnk" 2>nul
echo O HORIZONTE não vai mais iniciar com o Windows.
pause
