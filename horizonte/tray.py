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

    if "--reiniciando" in sys.argv:  # reinício após atualização: espera o anterior liberar a porta
        for _ in range(60):
            if not _port_busy(hz.settings.host, hz.settings.port):
                break
            time.sleep(0.5)

    if _port_busy(hz.settings.host, hz.settings.port):
        if _horizonte_alive(hz.settings.port):
            from .janela import abrir

            abrir(url, hz.settings.data_dir)  # já está aberto: só mostra a janela
            return
        _message_box("HORIZONTE", f"A porta {hz.settings.port} está sendo usada por outro programa.\n\n"
                                  "Abra o arquivo .env na pasta do HORIZONTE e troque HORIZONTE_PORT (ex.: 8788).")
        return

    import pystray
    import uvicorn
    from PIL import Image

    from . import notify, updater
    from .app import create_app
    from .pipeline import _CYCLE_LOCK, daily_cycle

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
        from .janela import abrir

        abrir(f"{url}/entrar?c={app.state.issue_login()}", hz.settings.data_dir)

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

    def restart_app(icon=None, item=None):
        updater.restart()
        quit_app(icon or state["icon"], item)

    def update_now(icon=None, item=None, manual=True):
        """Procura versão nova no GitHub; se houver, aplica e reinicia sozinho."""
        ic = icon or state["icon"]
        if not _CYCLE_LOCK.acquire(blocking=False):  # nunca atualiza no meio do ciclo
            if manual:
                ic.notify("O ciclo do dia está rodando. Tento atualizar quando ele terminar.", "HORIZONTE")
            return
        try:
            res = updater.apply(hz)
        except Exception as e:  # pragma: no cover - falha de rede/disco
            res = {"ok": False, "atualizado": False, "mensagem": f"Falha na atualização: {type(e).__name__}"}
        finally:
            _CYCLE_LOCK.release()
        if res.get("atualizado"):
            ic.notify(res["mensagem"] + " Reiniciando…", "HORIZONTE atualizado")
            time.sleep(2)
            restart_app(ic)
        elif manual:
            ic.notify(res["mensagem"], "HORIZONTE")

    def update_loop():
        time.sleep(60)
        while not state["quit"]:
            update_now(manual=False)
            for _ in range(3 * 3600 // 30):  # a cada 3 horas
                if state["quit"]:
                    return
                time.sleep(30)

    def update_click(icon, item):
        threading.Thread(target=lambda: update_now(icon), daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir HORIZONTE", open_panel, default=True),
        pystray.MenuItem("Abrir no navegador", lambda icon, item: webbrowser.open(f"{url}/entrar?c={app.state.issue_login()}")),
        pystray.MenuItem("Rodar ciclo do dia agora", run_cycle),
        pystray.MenuItem(lambda item: "Retomar operação" if hz.prefs()["pausado"] else "Pausar operação", toggle_pause),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Procurar atualização agora", update_click),
        pystray.MenuItem("Reiniciar HORIZONTE", restart_app),
        pystray.MenuItem("Sair do HORIZONTE", quit_app),
    )
    icon = pystray.Icon("HORIZONTE", Image.open(ICON), "HORIZONTE — Direito. Política. Sociedade.", menu)
    notify.set_tray(icon)
    state["icon"] = icon
    if os.environ.get("HORIZONTE_AUTO_UPDATE", "1") != "0":
        threading.Thread(target=update_loop, name="horizonte-atualizacao", daemon=True).start()

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
