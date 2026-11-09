"""Agendador local: roda as rotinas sozinho, sem execuções duplicadas, mesmo após reiniciar.

Cada execução registra (tarefa, faixa de horário) numa tabela com chave única.
Se o computador estava desligado no horário, a rotina do dia roda assim que ele ligar.
"""
from __future__ import annotations

import threading
import traceback
from datetime import date, datetime, timedelta

from . import editorial, linkedin, pipeline, radar, reports
from .db import dumps, now_iso


def _hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def claim(hz, job: str, slot: str) -> bool:
    """Reserva a execução; devolve False se essa faixa já rodou ou está rodando."""
    cur = hz.db.execute(
        "INSERT OR IGNORE INTO runs(job, slot, status, started_at) VALUES (?,?,?,?)", (job, slot, "em_execucao", now_iso())
    )
    return cur.rowcount == 1


def finish(hz, job: str, slot: str, status: str, details) -> None:
    hz.db.execute("UPDATE runs SET status=?, finished_at=?, details=? WHERE job=? AND slot=?",
                  (status, now_iso(), dumps(details)[:4000], job, slot))


def recover(hz) -> dict:
    """Na inicialização: execuções interrompidas liberam a faixa para rodar de novo."""
    stale = hz.db.query("SELECT job, slot FROM runs WHERE status='em_execucao'")
    for r in stale:
        hz.db.execute("DELETE FROM runs WHERE job=? AND slot=?", (r["job"], r["slot"]))
    posts = linkedin.recover_interrupted(hz)
    stuck = hz.db.execute("UPDATE stories SET status='selecionada' WHERE status='em_producao'").rowcount
    if stale or posts or stuck:
        hz.log("warning", "agendador",
               f"Recuperação: {len(stale)} rotina(s) interrompida(s), {posts} post(s) para conferir, {stuck} pauta(s) retomada(s).")
    return {"rotinas": len(stale), "posts": posts, "pautas": stuck}


def run_job(hz, job: str, slot: str, fn, *args) -> dict | None:
    if not claim(hz, job, slot):
        return None
    try:
        result = fn(hz, *args)
        finish(hz, job, slot, "ok", result)
        return result
    except Exception as e:  # a rotina nunca derruba o agendador
        hz.log("error", "agendador", f"{job} ({slot}) falhou: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
        finish(hz, job, slot, "falhou", {"erro": str(e)})
        return {"erro": str(e)}


def tick(hz, now: datetime | None = None) -> list[str]:
    """Uma verificação do relógio. Devolve as rotinas disparadas."""
    now = now or hz.local_now()
    prefs = hz.prefs()
    fired: list[str] = []
    if prefs["pausado"]:
        return fired
    today = now.date()

    interval = max(15, int(prefs["radar_intervalo_min"]))
    minutes = now.hour * 60 + now.minute
    radar_slot = f"{today.isoformat()}T{(minutes // interval) * interval // 60:02d}:{(minutes // interval) * interval % 60:02d}"

    h, m = _hhmm(prefs["horario_ciclo"])
    cycle_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= cycle_at:
        if run_job(hz, "ciclo", today.isoformat(), pipeline.daily_cycle, today.isoformat()) is not None:
            fired.append("ciclo")
            if claim(hz, "radar", radar_slot):  # o ciclo já passou pelo radar nesta faixa
                finish(hz, "radar", radar_slot, "ok", {"coberto_pelo_ciclo": True})
    # Ao longo do dia: completa pautas que faltaram (ex.: IA ligou depois do ciclo).
    if run_job(hz, "radar", radar_slot, _radar_and_refill, today.isoformat()) is not None:
        fired.append("radar")

    res = linkedin.publish_due(hz)
    if res.get("publicados") or res.get("falhas"):
        fired.append("publicador")

    h, m = _hhmm(prefs["horario_relatorio"])
    report_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= report_at:
        if run_job(hz, "relatorio", today.isoformat(), lambda hz_, d: reports.generate(hz_, "diario", d), today) is not None:
            fired.append("relatorio")
    yesterday = today - timedelta(days=1)
    if run_job(hz, "relatorio", yesterday.isoformat(), lambda hz_, d: reports.generate(hz_, "diario", d), yesterday) is not None:
        fired.append("relatorio_ontem")
    if today.weekday() == 0:
        prev_week = today - timedelta(days=7)
        if run_job(hz, "relatorio_semanal", prev_week.isoformat(), lambda hz_, d: reports.generate(hz_, "semanal", d), prev_week):
            fired.append("relatorio_semanal")
    if today.day == 1:
        prev_month = today - timedelta(days=1)
        if run_job(hz, "relatorio_mensal", prev_month.strftime("%Y-%m"), lambda hz_, d: reports.generate(hz_, "mensal", d), prev_month):
            fired.append("relatorio_mensal")
    return fired


def _radar_and_refill(hz, day: str) -> dict:
    out = {k: v for k, v in radar.run_radar(hz).items() if k != "por_fonte"}
    if hz.db.scalar("SELECT 1 FROM runs WHERE job='ciclo' AND slot=? AND status='ok'", (day,)):
        out["selecao"] = editorial.select_stories(hz, day)
        out["producao"] = editorial.produce_pending(hz, day)
    return out


class Scheduler:
    def __init__(self, hz, interval_seconds: int = 30):
        self.hz = hz
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick: str | None = None

    def start(self) -> None:
        recover(self.hz)
        self._thread = threading.Thread(target=self._loop, name="horizonte-agendador", daemon=True)
        self._thread.start()
        self.hz.log("info", "agendador", "Agendador iniciado.")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                tick(self.hz)
            except Exception as e:
                self.hz.log("error", "agendador", f"Falha no relógio: {e}")
            self.last_tick = now_iso()
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
