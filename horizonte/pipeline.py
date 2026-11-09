"""Ciclo diário do AGENTE HORIZONTE: monitorar → verificar → selecionar → produzir → distribuir."""
from __future__ import annotations

import threading

from . import editorial, linkedin, llm, radar, reports
from .notify import notify
from .db import dumps
from .verify import reverify_recent

_CYCLE_LOCK = threading.Lock()


def daily_cycle(hz, day: str | None = None) -> dict:
    """Roda o ciclo completo. Se outro ciclo já estiver rodando (agendador x botão), não roda em paralelo."""
    if not _CYCLE_LOCK.acquire(blocking=False):
        return {"ignorado": "Já há um ciclo em andamento."}
    try:
        return _daily_cycle(hz, day)
    finally:
        _CYCLE_LOCK.release()


def _daily_cycle(hz, day: str | None = None) -> dict:
    day = day or hz.today().isoformat()
    out: dict = {"dia": day}
    out["radar"] = {k: v for k, v in radar.run_radar(hz).items() if k != "por_fonte"}
    out["reverificados"] = reverify_recent(hz)
    out["selecao"] = editorial.select_stories(hz, day)
    ia = llm.status(hz)
    out["ia"] = {"pronta": ia["pronto"], "mensagem": ia["mensagem"]}
    if not ia["pronto"]:
        hz.log("warning", "ia", f"Produção editorial adiada: {ia['mensagem']}")
    out["producao"] = editorial.produce_pending(hz, day)
    out["linkedin"] = linkedin.publish_due(hz)
    xs = hz.db.scalar("SELECT COUNT(*) FROM posts p JOIN stories s ON s.id=p.story_id WHERE s.day=? AND p.network='x' AND p.status='pronto'", (day,)) or 0
    msg = f"{out['producao']['produzidas']} pauta(s) produzida(s). {xs} conteúdo(s) do X aguardando você."
    if not ia["pronto"]:
        msg = "IA local indisponível: as análises ficaram em espera. " + ia["mensagem"]
    notify(hz, "HORIZONTE — ciclo do dia", msg)
    st = linkedin.status(hz)
    if st["conectado"] and st["dias_restantes"] is not None and st["dias_restantes"] <= 7:
        notify(hz, "HORIZONTE — LinkedIn", f"A autorização do LinkedIn vence em {st['dias_restantes']} dia(s). Reconecte no painel.")
    hz.log("info", "agente", "Ciclo diário concluído: " + dumps(
        {"selecionadas": len(out["selecao"]["selecionadas"]), "produzidas": out["producao"]["produzidas"]}))
    return out


def end_of_day(hz, day=None) -> int:
    return reports.generate(hz, "diario", day)
