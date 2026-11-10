' Compatibilidade: abre o HORIZONTE na bandeja, sem janela.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" -m horizonte.tray --sem-navegador", 0, False
