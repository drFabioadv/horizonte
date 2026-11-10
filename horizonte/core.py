"""Contexto central: configurações, banco, cofre de tokens, logs e relógio local."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import httpx

from .config import DEFAULT_PREFS, Settings, load_settings
from .db import Database, now_iso
from .security import Vault, redact
from .sources import seed_sources


class Horizonte:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or load_settings()
        self.db = Database(self.settings.db_path)
        self.vault = Vault(self.settings.secret_key)
        self.tz = ZoneInfo(self.settings.timezone)
        self.transport = transport  # usado nos testes para simular a internet
        self._logger = logging.getLogger("horizonte")
        if not self._logger.handlers:
            handler = RotatingFileHandler(
                self.settings.data_dir / "horizonte.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
        seed_sources(self.db)
        if self.db.get_pref("ollama_modelo") in (None, ""):
            self.db.set_pref("ollama_modelo", self.settings.ollama_model)
        # a assinatura antiga "HORIZONTE — ..." deixava os posts com cara de página; agora o post é do autor
        if self.db.get_pref("assinatura") == "HORIZONTE — Direito. Política. Sociedade.":
            self.db.set_pref("assinatura", "")

    # ---------- preferências ----------
    def prefs(self) -> dict:
        return self.db.prefs(DEFAULT_PREFS)

    def set_prefs(self, values: dict) -> dict:
        for key, value in values.items():
            if key in DEFAULT_PREFS:
                self.db.set_pref(key, value)
        return self.prefs()

    # ---------- rede ----------
    def http(self, timeout: float = 20.0, **kwargs) -> httpx.Client:
        headers = {"User-Agent": self.settings.user_agent}
        headers.update(kwargs.pop("headers", {}))
        return httpx.Client(
            transport=self.transport, timeout=timeout, headers=headers, follow_redirects=True, **kwargs
        )

    # ---------- relógio ----------
    def local_now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.local_now().date()

    def day_bounds_utc(self, day: date) -> tuple[str, str]:
        start = datetime(day.year, day.month, day.day, tzinfo=self.tz)
        end = start + timedelta(days=1)
        return start.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"), end.astimezone(
            ZoneInfo("UTC")
        ).isoformat(timespec="seconds")

    # ---------- logs ----------
    def log(self, level: str, module: str, message: str) -> None:
        msg = redact(message)
        try:
            self.db.execute(
                "INSERT INTO logs(ts, level, module, message) VALUES (?,?,?,?)",
                (now_iso(), level.upper(), module, msg),
            )
        except Exception:  # o log nunca pode derrubar a rotina
            pass
        getattr(self._logger, level.lower() if level.lower() in ("info", "warning", "error") else "info")(
            f"[{module}] {msg}"
        )
