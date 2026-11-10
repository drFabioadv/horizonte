"""HORIZONTE como aplicativo: ícone na bandeja do Windows, sem janela de terminal.

Inicie com:  pythonw -m horizonte.tray   (é o que o atalho da área de trabalho faz)
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ICON = Path(__file__).parent / "assets" / "horizonte.png"


def _quiet_streams(data_dir: Path) -> None:
    """Sem console (pythonw), stdout/stderr não existem: manda tudo para um arquivo."""
    if sys.stdout is None or sys.stderr is None:
        f = open(data_dir / "horizonte-console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _message_box(title: str, text: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    else:
        print(f"{title}: {text}")


def main() -> None:
    from .__main__ import _horizonte_alive, _port_busy
    from .core import Horizonte

    hz = Horizonte()
    _quiet_streams(hz.settings.data_dir)
    url = hz.settings.public_url

    if _port_busy(hz.settings.host, hz.settings.port):
        if _horizonte_alive(hz.settings.port):
            webbrowser.open(url)  # já está aberto: só mostra o painel
            return
        _message_box("HORIZONTE", f"A porta {hz.settings.port} está sendo usada por outro programa.\n\n"
                                  "Abra o arquivo .env na pasta do HORIZONTE e troque HORIZONTE_PORT (ex.: 8788).")
        return

    import pystray
    import uvicorn
    from PIL import Image

    from . import notify
    from .app import create_app
    from .pipeline import daily_cycle

    app = create_app(hz)
    state = {"server": None, "quit": False}

    def serve_forever():
        """Mantém o servidor de pé; se cair, volta sozinho em 15 segundos."""
        while not state["quit"]:
            cfg = uvicorn.Config(app, host=hz.settings.host, port=hz.settings.port, log_level="warning",
                                 use_colors=False, log_config=None)
            server = uvicorn.Server(cfg)
            state["server"] = server
            try:
                server.run()
            except Exception as e:  # pragma: no cover - só em falhas reais
                hz.log("error", "bandeja", f"Servidor parou: {e}")
            if state["quit"]:
                break
            time.sleep(15)

    threading.Thread(target=serve_forever, name="horizonte-servidor", daemon=True).start()

    def open_panel(icon=None, item=None):
        webbrowser.open(f"{url}/entrar?c={app.state.issue_login()}")

    def run_cycle(icon, item):
        threading.Thread(target=lambda: daily_cycle(hz), daemon=True).start()
        icon.notify("Ciclo do dia iniciado. Você recebe um aviso quando terminar.", "HORIZONTE")

    def toggle_pause(icon, item):
        paused = not hz.prefs()["pausado"]
        hz.set_prefs({"pausado": paused})
        hz.log("info", "bandeja", "Operação pausada." if paused else "Operação retomada.")
        icon.update_menu()

    def quit_app(icon, item):
        state["quit"] = True
        if state["server"]:
            state["server"].should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", open_panel, default=True),
        pystray.MenuItem("Rodar ciclo do dia agora", run_cycle),
        pystray.MenuItem(lambda item: "Retomar operação" if hz.prefs()["pausado"] else "Pausar operação", toggle_pause),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair do HORIZONTE", quit_app),
    )
    icon = pystray.Icon("HORIZONTE", Image.open(ICON), "HORIZONTE — Direito. Política. Sociedade.", menu)
    notify.set_tray(icon)

    def ready(icon):
        icon.visible = True
        if "--sem-navegador" not in sys.argv:
            for _ in range(40):  # espera o servidor responder antes de abrir o navegador
                if _horizonte_alive(hz.settings.port):
                    open_panel()
                    break
                time.sleep(0.5)

    icon.run(setup=ready)


if __name__ == "__main__":
    main()
