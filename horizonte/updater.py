"""Atualização automática pelo GitHub (igual ao JARVIS): sem reinstalar.

O HORIZONTE consulta o repositório público, baixa o código novo em .zip e troca só
os arquivos do programa. Nunca toca no .env, na pasta data/ (banco, chaves, relatórios)
nem no ambiente Python (.venv). Se o requirements.txt mudar, instala as dependências novas.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx

from .config import BASE_DIR

PROTECTED = {".env", "data", ".venv", "venv", "backup", ".git", "__pycache__"}


def repo(hz) -> str:
    return os.environ.get("HORIZONTE_UPDATE_REPO", "drFabioadv/horizonte").strip()


def _version_file(hz) -> Path:
    return hz.settings.data_dir / "versao.txt"


def installed(hz) -> str:
    p = _version_file(hz)
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def check(hz) -> dict:
    """Pergunta ao GitHub qual é a versão mais nova (último commit da branch main)."""
    r_name = repo(hz)
    if not r_name:
        return {"ok": False, "mensagem": "Atualização automática desligada (HORIZONTE_UPDATE_REPO vazio)."}
    try:
        with hz.http(timeout=15) as client:
            r = client.get(f"https://api.github.com/repos/{r_name}/commits/main",
                           headers={"Accept": "application/vnd.github+json"})
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Sem conexão com o GitHub ({type(e).__name__})."}
    if r.status_code != 200:
        return {"ok": False, "mensagem": f"Não encontrei o repositório {r_name} (HTTP {r.status_code})."}
    data = r.json()
    sha = data.get("sha", "")
    msg = (data.get("commit", {}).get("message") or "").splitlines()[0][:120]
    atual = installed(hz)
    return {"ok": True, "disponivel": bool(sha) and sha != atual, "versao": sha, "instalada": atual, "mensagem": msg}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def apply(hz, target: Path | None = None, run_pip: bool = True) -> dict:
    """Baixa e aplica a versão mais nova. Devolve {"ok", "atualizado", "arquivos", "mensagem"}."""
    info = check(hz)
    if not info.get("ok"):
        return {"ok": False, "atualizado": False, "mensagem": info["mensagem"]}
    if not info["disponivel"]:
        return {"ok": True, "atualizado": False, "mensagem": "O HORIZONTE já está na versão mais nova."}
    target = Path(target or BASE_DIR)
    with hz.http(timeout=120) as client:
        r = client.get(f"https://codeload.github.com/{repo(hz)}/zip/{info['versao']}")
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return {"ok": False, "atualizado": False, "mensagem": f"Falha ao baixar a atualização (HTTP {r.status_code})."}

    req_before = _digest(target / "requirements.txt")
    changed = 0
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for member in z.infolist():
            parts = Path(member.filename).parts[1:]  # tira a pasta "horizonte-<sha>/"
            if not parts or member.is_dir() or parts[0] in PROTECTED or "__pycache__" in parts:
                continue
            if any(p in ("..", "") for p in parts):
                continue
            dest = target.joinpath(*parts)
            data = z.read(member)
            if dest.exists() and dest.read_bytes() == data:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".novo")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            changed += 1

    pip_msg = ""
    if run_pip and _digest(target / "requirements.txt") != req_before:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(target / "requirements.txt")],
                           cwd=target, timeout=900, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pip_msg = " Dependências atualizadas."
        except (OSError, subprocess.SubprocessError) as e:
            pip_msg = f" Aviso: não consegui atualizar as dependências ({type(e).__name__})."
    _version_file(hz).write_text(info["versao"], encoding="utf-8")
    hz.log("info", "atualizacao", f"Atualizado para {info['versao'][:7]} ({changed} arquivos): {info['mensagem']}")
    return {"ok": True, "atualizado": True, "arquivos": changed, "versao": info["versao"],
            "mensagem": f"Atualizado: {info['mensagem']}.{pip_msg}"}


def restart() -> None:
    """Abre um HORIZONTE novo (que espera este fechar e liberar a porta)."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if pyw.exists() else exe), "-m", "horizonte.tray", "--sem-navegador", "--reiniciando"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, cwd=str(BASE_DIR), creationflags=flags, close_fds=True)
