# Cria ou remove os atalhos do HORIZONTE (area de trabalho, menu Iniciar, inicializacao do Windows)
param([string]$Modo = "criar")
$raiz = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$ico = Join-Path $raiz "horizonte\assets\horizonte.ico"
$shell = New-Object -ComObject WScript.Shell

function Novo-Atalho($caminho, $argumentos) {
    $s = $shell.CreateShortcut($caminho)
    $s.TargetPath = $pyw
    $s.Arguments = $argumentos
    $s.WorkingDirectory = $raiz
    $s.IconLocation = "$ico,0"
    $s.Description = "HORIZONTE - Direito. Politica. Sociedade."
    $s.Save()
}

$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "HORIZONTE.lnk"
$menu = Join-Path ([Environment]::GetFolderPath("Programs")) "HORIZONTE.lnk"
$inicio = Join-Path ([Environment]::GetFolderPath("Startup")) "HORIZONTE.lnk"

if ($Modo -eq "criar") {
    if (-not (Test-Path $pyw)) { Write-Host "Rode instalar.bat primeiro."; exit 1 }
    Novo-Atalho $desktop "-m horizonte.tray"
    Novo-Atalho $menu "-m horizonte.tray"
    Write-Host "Atalhos criados na area de trabalho e no menu Iniciar."
}
elseif ($Modo -eq "inicio") {
    Novo-Atalho $inicio "-m horizonte.tray --sem-navegador"
    Write-Host "O HORIZONTE vai iniciar sozinho com o Windows (icone na bandeja, sem janela)."
}
elseif ($Modo -eq "remover-inicio") {
    Remove-Item $inicio -ErrorAction SilentlyContinue
    Write-Host "Inicio automatico removido."
}
