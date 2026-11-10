"""Janela própria do HORIZONTE (fora do navegador comum).

Usa o modo "aplicativo" do Microsoft Edge, que já vem no Windows: abre uma janela sem abas,
sem barra de endereço e com o ícone do HORIZONTE, usando um perfil só dele (separado do seu
navegador). É o mesmo motor do Edge, então é tão rápido quanto o navegador.
Se não houver Edge nem Chrome, cai no navegador padrão.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path


def _browser() -> str | None:
    candidatos = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidatos += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                           Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    for c in candidatos:
        if c.exists():
            return str(c)
    for nome in ("msedge", "google-chrome", "chromium", "chromium-browser"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def command(url: str, data_dir: Path, exe: str | None) -> list[str]:
    perfil = Path(data_dir) / "janela"
    perfil.mkdir(parents=True, exist_ok=True)
    return [exe, f"--app={url}", f"--user-data-dir={perfil}", "--window-size=1440,920",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]


def abrir(url: str, data_dir: Path) -> bool:
    """Abre (ou traz para a frente) a janela do HORIZONTE. Devolve False se usou o navegador comum."""
    exe = _browser()
    if exe:
        try:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(command(url, data_dir, exe), creationflags=flags, close_fds=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    webbrowser.open(url)
    return False
