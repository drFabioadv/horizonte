' Inicia o HORIZONTE sem janela (usado pelo inicio automatico do Windows).
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
sh.Run """" & dir & "\iniciar.bat"" --sem-navegador", 0, False
