"""Central de Publicações do X: conteúdos preparados para publicação MANUAL.

O HORIZONTE nunca publica no X nem afirma que publicou: só o usuário marca
um conteúdo como publicado.
"""
from __future__ import annotations

from .db import loads, now_iso, row_dict
from .textutil import x_length

LABEL = {"pronto": "PRONTO PARA PUBLICAR", "publicado_manual": "PUBLICADO MANUALMENTE", "descartado": "DESCARTADO"}


def list_items(hz, day: str | None = None, status: str | None = None, limit: int = 60) -> list[dict]:
    sql = "SELECT p.*, s.day FROM posts p LEFT JOIN stories s ON s.id=p.story_id WHERE p.network='x'"
    params: list = []
    if day:
        sql += " AND s.day=?"
        params.append(day)
    if status:
        sql += " AND p.status=?"
        params.append(status)
    sql += " ORDER BY p.created_at DESC LIMIT ?"
    params.append(limit)
    out = []
    for r in hz.db.query(sql, params):
        d = row_dict(r, ("hashtags", "sources", "thread", "image"))
        d["situacao"] = LABEL.get(d["status"], d["status"])
        d["caracteres"] = x_length(d["body"])
        d["thread_caracteres"] = [x_length(t) for t in d.get("thread") or []]
        out.append(d)
    return out


def mark(hz, post_id: int, published: bool, url: str | None = None) -> dict:
    row = hz.db.one("SELECT id FROM posts WHERE id=? AND network='x'", (post_id,))
    if not row:
        return {"ok": False, "mensagem": "Conteúdo não encontrado."}
    if published:
        hz.db.execute(
            "UPDATE posts SET status='publicado_manual', published_at=?, external_url=?, updated_at=? WHERE id=?",
            (now_iso(), url or None, now_iso(), post_id),
        )
    else:
        hz.db.execute(
            "UPDATE posts SET status='pronto', published_at=NULL, external_url=NULL, updated_at=? WHERE id=?",
            (now_iso(), post_id),
        )
    return {"ok": True}


def discard(hz, post_id: int) -> dict:
    hz.db.execute("UPDATE posts SET status='descartado', updated_at=? WHERE id=? AND network='x'", (now_iso(), post_id))
    return {"ok": True}
