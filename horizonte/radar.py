"""Radar de notícias: lê os feeds RSS, normaliza, deduplica e classifica."""
from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import httpx

from .classify import classify
from .db import dumps, now_iso
from .sources import discover_feed
from .textutil import canonical_url, norm_title, strip_html
from .verify import assign_clusters

MAX_ITEMS_PER_FEED = 60


def _entry_date(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc).isoformat(timespec="seconds")
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def _entry_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key) or []:
            url = m.get("url")
            if url and (m.get("medium") in (None, "image") or key == "media_thumbnail"):
                return url
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    return None


def parse_feed(content: bytes) -> list[dict]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        title = strip_html(entry.get("title"))
        link = entry.get("link")
        if not title or not link:
            continue
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        items.append({
            "title": title[:400],
            "url": link,
            "summary": summary[:1500],
            "author": strip_html(entry.get("author") or "")[:200] or None,
            "published_at": _entry_date(entry),
            "image_url": _entry_image(entry),
        })
    return items


def fetch_source(hz, source: dict, client: httpx.Client) -> tuple[list[dict], str, str | None]:
    """Baixa um feed respeitando ETag/Last-Modified. Retorna (itens, status, erro)."""
    headers = {}
    if source.get("etag"):
        headers["If-None-Match"] = source["etag"]
    if source.get("last_modified"):
        headers["If-Modified-Since"] = source["last_modified"]
    try:
        r = client.get(source["feed_url"], headers=headers)
    except httpx.HTTPError as e:
        return [], "erro", f"Falha de conexão: {type(e).__name__}"
    if r.status_code == 304:
        return [], "sem_novidades", None
    if r.status_code >= 400:
        return [], "erro", f"HTTP {r.status_code}"
    items = parse_feed(r.content)
    hz.db.execute(
        "UPDATE sources SET etag=?, last_modified=? WHERE id=?",
        (r.headers.get("etag"), r.headers.get("last-modified"), source["id"]),
    )
    if not items:
        return [], "vazio", "O feed respondeu, mas não trouxe notícias."
    return items, "ok", None


def store_items(hz, source: dict, items: list[dict]) -> list[int]:
    new_ids: list[int] = []
    fetched = now_iso()
    with hz.db.tx() as conn:
        for it in items:
            canon = canonical_url(it["url"])
            info = classify(it["title"], it["summary"], source)
            cur = conn.execute(
                "INSERT OR IGNORE INTO news(source_id, url, url_canon, title, title_norm, summary, author, published_at, "
                "fetched_at, category, category_scores, region, relevance, flags, image_url) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source["id"], it["url"], canon, it["title"], norm_title(it["title"]), it["summary"], it["author"],
                 it["published_at"], fetched, info["category"], dumps(info["scores"]), info["region"],
                 info["relevance"], dumps(info["flags"]), it["image_url"]),
            )
            if cur.rowcount:
                new_ids.append(cur.lastrowid)
    return new_ids


def run_radar(hz, source_ids: list[int] | None = None) -> dict:
    """Uma passada do radar por todas as fontes ligadas."""
    sql = "SELECT * FROM sources WHERE enabled=1 AND feed_url IS NOT NULL"
    params: list = []
    if source_ids:
        sql += f" AND id IN ({','.join('?' * len(source_ids))})"
        params = list(source_ids)
    sources = [dict(r) for r in hz.db.query(sql, params)]
    summary = {"fontes": len(sources), "novas": 0, "erros": 0, "por_fonte": []}
    with hz.http(timeout=20) as client:
        def work(src):
            return src, fetch_source(hz, src, client)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(work, sources))
    all_new: list[int] = []
    for src, (items, status, error) in results:
        new_ids = store_items(hz, src, items) if items else []
        all_new += new_ids
        hz.db.execute(
            "UPDATE sources SET last_checked=?, last_status=?, last_error=?, items_total=items_total+? WHERE id=?",
            (now_iso(), status, error, len(new_ids), src["id"]),
        )
        if error:
            summary["erros"] += 1
            hz.log("warning", "radar", f"{src['name']}: {error}")
        summary["por_fonte"].append({"fonte": src["name"], "status": status, "novas": len(new_ids), "erro": error})
    summary["novas"] = len(all_new)
    if all_new:
        summary["agrupamento"] = assign_clusters(hz, all_new)
    hz.log("info", "radar", f"Radar: {summary['novas']} notícias novas de {summary['fontes']} fontes ({summary['erros']} com erro).")
    return summary


def test_source(hz, source_id: int) -> dict:
    """Testa uma fonte e tenta descobrir o feed automaticamente."""
    src = hz.db.one("SELECT * FROM sources WHERE id=?", (source_id,))
    if not src:
        return {"ok": False, "mensagem": "Fonte não encontrada."}
    src = dict(src)
    with hz.http(timeout=15) as client:
        feed, msg = discover_feed(client, src["homepage"], src.get("feed_url"))
    status = "ok" if feed else "sem_feed"
    hz.db.execute(
        "UPDATE sources SET feed_url=COALESCE(?, feed_url), last_checked=?, last_status=?, last_error=? WHERE id=?",
        (feed, now_iso(), status, None if feed else msg, source_id),
    )
    return {"ok": bool(feed), "feed_url": feed, "mensagem": msg}
