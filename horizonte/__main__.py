"""Inicia o HORIZONTE: python -m horizonte"""
from __future__ import annotations

import argparse
import webbrowser

import uvicorn

from .app import create_app
from .core import Horizonte


def main() -> None:
    parser = argparse.ArgumentParser(description="HORIZONTE — central editorial local")
    parser.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador ao iniciar")
    parser.add_argument("--ciclo-agora", action="store_true", help="roda o ciclo diário uma vez e sai")
    args = parser.parse_args()

    hz = Horizonte()
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
    uvicorn.run(app, host=hz.settings.host, port=hz.settings.port, log_level="warning")


if __name__ == "__main__":
    main()
