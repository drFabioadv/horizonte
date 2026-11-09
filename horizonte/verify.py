"""Agrupamento de notícias sobre o mesmo fato e verificação por fontes.

A verificação não pergunta à IA se algo é verdade: ela confere evidências
objetivas — fonte primária, confirmação por veículos independentes, data
e sinais de contestação.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from .db import dumps, loads, now_iso, utcnow
from .textutil import tokens

WINDOW_HOURS = 48
MAX_MEMBERS = 12

VERIFICADA = "VERIFICADA"
EM_CONFERENCIA = "EM CONFERÊNCIA"
CONTROVERSA = "CONTROVERSA"
NAO_PUBLICAR = "NÃO PUBLICAR"


def _weighted(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """Semelhança ponderada: palavras raras (nomes, temas) pesam mais que as comuns."""
    if not a or not b:
        return 0.0
    w = lambda ws: sum(idf.get(t, 3.0) for t in ws)
    inter = w(a & b)
    sim = inter / w(a | b)
    if min(len(a), len(b)) >= 4 and len(a & b) >= 3:
        sim = max(sim, 0.75 * inter / min(w(a), w(b)))
    return sim


def _similar(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    shared = a & b
    if len(shared) < 2:
        return 0.0
    sim = _weighted(a, b, idf)
    rare = sum(1 for t in shared if idf.get(t, 3.0) >= 3.5)
    if len(shared) >= 3 and sim >= 0.34:
        return sim
    if rare >= 2 and sim >= 0.45:
        return sim
    return 0.0


def _idf(hz, since: str) -> dict[str, float]:
    df: Counter = Counter()
    rows = hz.db.query("SELECT title FROM news WHERE fetched_at >= ?", (since,))
    for r in rows:
        df.update(tokens(r["title"]))
    n = max(1, len(rows))
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


MAX_GAP = timedelta(hours=36)


def assign_clusters(hz, news_ids: list[int]) -> dict:
    """Coloca cada notícia nova num grupo existente (mesmo fato) ou cria um grupo."""
    since = (utcnow() - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")
    clusters: dict[int, dict] = {}
    for r in hz.db.query("SELECT id, tokens, newest_published, first_seen FROM clusters WHERE last_seen >= ?", (since,)):
        clusters[r["id"]] = {"members": [set(m) for m in loads(r["tokens"], [])],
                             "t": _parse(r["newest_published"]) or _parse(r["first_seen"])}
    idf = _idf(hz, since)
    touched: set[int] = set()
    created = 0
    rows = hz.db.query(
        f"SELECT id, title, published_at, fetched_at FROM news WHERE id IN ({','.join('?' * len(news_ids))}) "
        "ORDER BY COALESCE(published_at, fetched_at)",
        news_ids,
    )
    for row in rows:
        tk = tokens(row["title"])
        t_item = _parse(row["published_at"]) or _parse(row["fetched_at"])
        best, best_sim = None, 0.0
        if len(tk) >= 4:  # títulos muito curtos ("Últimas notícias") não agrupam
            for cid, c in clusters.items():
                if c["t"] and t_item and abs(c["t"] - t_item) > MAX_GAP:
                    continue
                for m in c["members"]:
                    sim = _similar(tk, m, idf)
                    if sim > best_sim:
                        best, best_sim = cid, sim
        now = now_iso()
        if best is None:
            with hz.db.tx() as conn:
                cur = conn.execute(
                    "INSERT INTO clusters(tokens, title, first_seen, last_seen, updated_at) VALUES (?,?,?,?,?)",
                    (dumps([sorted(tk)]), row["title"], now, now, now),
                )
                cid = cur.lastrowid
                conn.execute("UPDATE news SET cluster_id=? WHERE id=?", (cid, row["id"]))
            clusters[cid] = {"members": [tk], "t": t_item}
            created += 1
        else:
            cid = best
            c = clusters[cid]
            if len(c["members"]) < MAX_MEMBERS:
                c["members"].append(tk)
            if t_item and (c["t"] is None or t_item > c["t"]):
                c["t"] = t_item
            has_story = hz.db.scalar("SELECT 1 FROM stories WHERE cluster_id=?", (cid,))
            with hz.db.tx() as conn:
                conn.execute(
                    "UPDATE clusters SET tokens=?, last_seen=? WHERE id=?",
                    (dumps([sorted(m) for m in c["members"]]), now, cid),
                )
                conn.execute(
                    "UPDATE news SET cluster_id=?, is_update=? WHERE id=?", (cid, 1 if has_story else 0, row["id"])
                )
        touched.add(cid)
    for cid in touched:
        verify_cluster(hz, cid)
    return {"grupos_novos": created, "grupos_atualizados": len(touched) - created}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def verify_cluster(hz, cluster_id: int) -> dict:
    items = [
        dict(r)
        for r in hz.db.query(
            "SELECT n.*, s.org, s.tier, s.name AS source_name FROM news n JOIN sources s ON s.id=n.source_id "
            "WHERE n.cluster_id=? ORDER BY n.relevance DESC",
            (cluster_id,),
        )
    ]
    if not items:
        return {}
    prefs = hz.prefs()
    max_age = timedelta(hours=int(prefs.get("idade_maxima_horas", 48)))
    now = utcnow()

    orgs = {i["org"] for i in items}
    tiers = {i["tier"] for i in items}
    has_primary = "primaria" in tiers
    flags: set[str] = set()
    for i in items:
        flags |= set(loads(i["flags"], []))
    dated = [d for d in (_parse(i["published_at"]) for i in items) if d]
    newest = max(dated) if dated else None
    undated = not dated

    cat_score: Counter = Counter()
    for i in items:
        for cat, sc in loads(i["category_scores"], {}).items():
            cat_score[cat] += sc
        cat_score[i["category"]] += 1
    category = cat_score.most_common(1)[0][0]
    region = "PA" if any(i["region"] == "PA" for i in items) else "BR"

    notes: list[str] = []
    n_orgs = len(orgs)
    notes.append(f"{len(items)} registro(s) de {n_orgs} veículo(s)/órgão(s) independente(s).")
    if has_primary:
        notes.append("Há fonte primária (o próprio órgão ou instituição).")

    all_opinion = all("opiniao_ou_midia" in loads(i["flags"], []) for i in items)
    low_value = all(i["relevance"] <= 10 for i in items)
    hours = int(max_age.total_seconds() // 3600)

    if newest and now - newest > max_age:
        status = NAO_PUBLICAR
        notes.append(f"Notícia antiga: publicada em {newest.date().isoformat()}, fora da janela de {hours} horas.")
    elif all_opinion:
        status = NAO_PUBLICAR
        notes.append("Só há conteúdo de opinião, áudio ou vídeo; não serve de base factual.")
    elif low_value:
        status = NAO_PUBLICAR
        notes.append("Sem relevância pública suficiente para a linha editorial.")
    elif "contestacao" in flags and n_orgs >= 2:
        status = CONTROVERSA
        notes.append("Há versões em disputa entre as fontes (negação, contestação ou desmentido).")
    elif "acusacao" in flags:
        if has_primary or n_orgs >= 3:
            status = VERIFICADA
            notes.append("Envolve acusação: o fato da investigação/denúncia está confirmado, não a culpa. Respeitar a presunção de inocência.")
        else:
            status = EM_CONFERENCIA
            notes.append("Envolve acusação grave sem fonte primária nem três veículos independentes. Aguardando confirmação.")
    elif has_primary or n_orgs >= 2:
        status = VERIFICADA
    elif tiers == {"publica"} and not ({"sensivel"} & flags):
        status = VERIFICADA
        notes.append("Fonte: agência pública de notícias (EBC); confirmação independente recomendada para detalhes.")
    else:
        status = EM_CONFERENCIA
        notes.append("Uma única fonte jornalística; aguardando confirmação independente. Ausência de confirmação não significa que a notícia seja falsa.")

    if undated:
        notes.append("O feed não informa data de publicação; usada a data da primeira leitura.")
        if status == VERIFICADA and not has_primary and n_orgs < 2:
            status = EM_CONFERENCIA
    if "proposicao" in flags:
        notes.append("Trata de proposição (projeto, PEC ou MP): não apresentar como lei aprovada.")
    if "decisao_provisoria" in flags:
        notes.append("Decisão provisória (liminar/monocrática): pode ser revista.")

    best_rel = max(i["relevance"] for i in items)
    score = best_rel + min(24, 8 * (n_orgs - 1)) + (10 if has_primary else 0)
    if newest and now - newest <= timedelta(hours=12):
        score += 8
    if status != VERIFICADA:
        score -= 30

    newest_iso = newest.isoformat(timespec="seconds") if newest else None
    hz.db.execute(
        "UPDATE clusters SET title=?, category=?, region=?, newest_published=?, n_items=?, n_orgs=?, has_primary=?, "
        "verification=?, verification_notes=?, flags=?, score=?, updated_at=? WHERE id=?",
        (items[0]["title"], category, region, newest_iso, len(items), n_orgs, int(has_primary), status,
         dumps(notes), dumps(sorted(flags)), score, now_iso(), cluster_id),
    )
    return {"status": status, "notes": notes, "score": score, "category": category}


def reverify_recent(hz, hours: int = 72) -> int:
    """Reavalia grupos recentes (a idade da notícia muda o status com o tempo)."""
    since = (utcnow() - timedelta(hours=hours)).isoformat(timespec="seconds")
    ids = [r["id"] for r in hz.db.query("SELECT id FROM clusters WHERE last_seen >= ?", (since,))]
    for cid in ids:
        verify_cluster(hz, cid)
    return len(ids)
