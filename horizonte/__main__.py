"""Inicia o HORIZONTE: python -m horizonte"""
from __future__ import annotations

import argparse
import socket
import sys
import urllib.request
import webbrowser

import uvicorn

from .app import create_app
from .core import Horizonte


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1" if host in ("0.0.0.0", "") else host, port)) == 0


def _horizonte_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/saude", timeout=3) as r:
            return b'"ok"' in r.read()
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="HORIZONTE — central editorial local")
    parser.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador ao iniciar")
    parser.add_argument("--ciclo-agora", action="store_true", help="roda o ciclo diário uma vez e sai")
    args = parser.parse_args()

    hz = Horizonte()
    if not args.ciclo_agora and _port_busy(hz.settings.host, hz.settings.port):
        if _horizonte_alive(hz.settings.port):
            print("O HORIZONTE já está rodando neste computador.")
            print(f"Abra o painel em {hz.settings.public_url}")
            if not args.sem_navegador:
                webbrowser.open(hz.settings.public_url)
            sys.exit(3)
        print(f"A porta {hz.settings.port} está sendo usada por outro programa.")
        print("Mude HORIZONTE_PORT no arquivo .env (ex.: 8788) e o endereço de retorno no app do LinkedIn.")
        sys.exit(4)
    if args.ciclo_agora:
        from .pipeline import daily_cycle

        print(daily_cycle(hz))
        return
    print("=" * 64)
    print(" HORIZONTE — Direito. Política. Sociedade.")
    print(f" Painel: {hz.settings.public_url}")
    print(f" Chave do painel: {hz.settings.admin_token}")
    print("   (também está em data/admin.token, ou defina HORIZONTE_ADMIN_TOKEN no .env)")
    print("=" * 64)
    app = create_app(hz)
    if not args.sem_navegador:
        try:
            webbrowser.open(hz.settings.public_url)
        except Exception:
            pass
    uvicorn.run(app, host=hz.settings.host, port=hz.settings.port, log_level="warning", use_colors=False)


if __name__ == "__main__":
    main()
