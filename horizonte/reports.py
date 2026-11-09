"""RELATÓRIO DIÁRIO HORIZONTE (e versões semanal e mensal), com exportação em PDF e CSV."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from .db import dumps, loads, now_iso
from .editorial import CATEGORY_LABEL

STATUS_LI = {"agendado": "Agendado", "publicado": "Publicado", "falhou": "Falhou", "suspenso": "Suspenso",
             "verificar": "Conferir no LinkedIn", "publicando": "Publicando", "cancelado": "Cancelado"}
STATUS_X = {"pronto": "Aguardando publicação manual", "publicado_manual": "Marcado como publicado",
            "descartado": "Descartado"}


def period(kind: str, day: date) -> tuple[date, date]:
    if kind == "diario":
        return day, day
    if kind == "semanal":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    start = day.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def build(hz, kind: str, day: date) -> dict:
    start, end = period(kind, day)
    a, _ = hz.day_bounds_utc(start)
    _, b = hz.day_bounds_utc(end)
    q = hz.db.query
    n_news = hz.db.scalar("SELECT COUNT(*) FROM news WHERE fetched_at>=? AND fetched_at<?", (a, b))
    stories = [dict(r) for r in q("SELECT * FROM stories WHERE day>=? AND day<=?", (start.isoformat(), end.isoformat()))]
    n_verified = hz.db.scalar(
        "SELECT COUNT(*) FROM clusters WHERE first_seen>=? AND first_seen<? AND verification='VERIFICADA'", (a, b))
    posts = [dict(r) for r in q(
        "SELECT p.* FROM posts p LEFT JOIN stories s ON s.id=p.story_id "
        "WHERE (s.day>=? AND s.day<=?) OR (p.story_id IS NULL AND p.created_at>=? AND p.created_at<?) ORDER BY p.created_at",
        (start.isoformat(), end.isoformat(), a, b))]
    cats = {k: 0 for k in CATEGORY_LABEL}
    for s in stories:
        if s["category"] in cats and s["status"] not in ("descartada",):
            cats[s["category"]] += 1

    def li_item(p):
        return {"titulo": p["title"], "texto": p["body"], "categoria": CATEGORY_LABEL.get(p["category"], p["category"] or "—"),
                "data_hora": p["published_at"] or p["scheduled_for"], "link": p["external_url"],
                "fontes": loads(p["sources"], []), "situacao": STATUS_LI.get(p["status"], p["status"]), "erro": p["error"]}

    def x_item(p):
        img = loads(p["image"], None)
        return {"titulo": p["title"], "texto": p["body"], "thread": loads(p["thread"], []), "hashtags": loads(p["hashtags"], []),
                "fontes": loads(p["sources"], []), "link": (loads(p["sources"], []) or [{}])[0].get("url"),
                "poster": img if img and img.get("autorizada") else None,
                "restricao_imagem": img.get("observacao") if img and not img.get("autorizada") else None,
                "situacao": STATUS_X.get(p["status"], p["status"])}

    li = [li_item(p) for p in posts if p["network"] == "linkedin"]
    xs = [x_item(p) for p in posts if p["network"] == "x"]
    discarded = [dict(r) for r in q(
        "SELECT title, verification, verification_notes FROM clusters WHERE first_seen>=? AND first_seen<? "
        "AND verification IN ('NÃO PUBLICAR','CONTROVERSA') AND flags NOT LIKE '%titulo_curto%' "
        "ORDER BY score DESC LIMIT 12", (a, b))]
    n_discarded = hz.db.scalar(
        "SELECT COUNT(*) FROM clusters WHERE first_seen>=? AND first_seen<? AND verification IN ('NÃO PUBLICAR','CONTROVERSA')",
        (a, b)) or 0
    errors = [dict(r) for r in q(
        "SELECT ts, module, message FROM logs WHERE ts>=? AND ts<? AND level='ERROR' ORDER BY ts", (a, b))]
    src_err = [dict(r) for r in q("SELECT name, last_error FROM sources WHERE enabled=1 AND last_error IS NOT NULL")]
    data = {
        "tipo": kind,
        "titulo": {"diario": "RELATÓRIO DIÁRIO HORIZONTE", "semanal": "RELATÓRIO SEMANAL HORIZONTE",
                   "mensal": "RELATÓRIO MENSAL HORIZONTE"}[kind],
        "periodo": {"inicio": start.isoformat(), "fim": end.isoformat()},
        "gerado_em": now_iso(),
        "resumo": {
            "noticias_monitoradas": n_news or 0,
            "pautas_selecionadas": len(stories),
            "pautas_verificadas": n_verified or 0,
            "conteudos_produzidos": len(posts),
            "linkedin_publicados": sum(1 for p in posts if p["network"] == "linkedin" and p["status"] == "publicado"),
            "x_preparados": len(xs),
            "noticias_descartadas": n_discarded,
            "categorias": {CATEGORY_LABEL[k]: v for k, v in cats.items()},
        },
        "linkedin": li,
        "x": xs,
        "ocorrencias": {
            "publicacoes_nao_realizadas": [
                {"titulo": i["titulo"], "situacao": i["situacao"], "motivo": i["erro"]}
                for i in li if i["situacao"] not in ("Publicado",)
            ],
            "pautas_suspensas": [{"pauta": s["id"], "motivo": s["reason"]} for s in stories
                                 if s["status"] in ("suspensa", "aguardando_ia")],
            "noticias_descartadas": [{"titulo": d["title"], "status": d["verification"],
                                      "motivo": (loads(d["verification_notes"], []) or [""])[-1]} for d in discarded],
            "restricoes_de_imagem": [{"titulo": i["titulo"], "motivo": i["restricao_imagem"]} for i in xs if i["restricao_imagem"]],
            "falhas_de_integracao": [e for e in errors if e["module"] in ("linkedin", "ia")],
            "problemas_tecnicos": [e for e in errors if e["module"] not in ("linkedin", "ia")],
            "fontes_com_erro": src_err,
        },
    }
    return data


def generate(hz, kind: str = "diario", day: date | None = None) -> int:
    day = day or hz.today()
    data = build(hz, kind, day)
    start, end = period(kind, day)
    hz.db.execute(
        "INSERT INTO reports(kind, period_start, period_end, data, created_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(kind, period_start) DO UPDATE SET data=excluded.data, period_end=excluded.period_end, created_at=excluded.created_at",
        (kind, start.isoformat(), end.isoformat(), dumps(data), now_iso()),
    )
    rid = hz.db.scalar("SELECT id FROM reports WHERE kind=? AND period_start=?", (kind, start.isoformat()))
    hz.log("info", "relatorios", f"{data['titulo']} gerado para {start.isoformat()}.")
    return rid


# ---------------------------------------------------------------- exportação


def _fmt(hz, iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).astimezone(hz.tz).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def to_csv(hz, data: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["rede", "titulo", "categoria", "situacao", "data_hora", "link", "fontes", "texto"])
    for i in data["linkedin"]:
        w.writerow(["LinkedIn", i["titulo"], i["categoria"], i["situacao"], _fmt(hz, i["data_hora"]), i["link"] or "",
                    " | ".join(f"{s['veiculo']} {s['url']}" for s in i["fontes"]), i["texto"]])
    for i in data["x"]:
        w.writerow(["X", i["titulo"], "", i["situacao"], "", i["link"] or "",
                    " | ".join(f"{s['veiculo']} {s['url']}" for s in i["fontes"]),
                    i["texto"] if not i["thread"] else "\n---\n".join(i["thread"])])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_pdf(hz, data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    ink, gold, muted = colors.HexColor("#10192b"), colors.HexColor("#b8862f"), colors.HexColor("#5b6578")
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17, textColor=ink, alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=base["Normal"], fontName="Helvetica", fontSize=9, textColor=muted, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=gold, spaceBefore=12, spaceAfter=6)
    h3 = ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10, textColor=ink, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica", fontSize=9, leading=12.5, textColor=ink)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=muted, leading=11)

    def P(text, st=body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st)

    story = [P(data["titulo"], h1),
             P(f"HORIZONTE — Direito. Política. Sociedade. · Período: {data['periodo']['inicio']} a {data['periodo']['fim']} · "
               f"Gerado em {_fmt(hz, data['gerado_em'])}", sub)]
    r = data["resumo"]
    rows = [["Notícias monitoradas", r["noticias_monitoradas"]], ["Pautas selecionadas", r["pautas_selecionadas"]],
            ["Pautas verificadas", r["pautas_verificadas"]], ["Conteúdos produzidos", r["conteudos_produzidos"]],
            ["Publicados no LinkedIn", r["linkedin_publicados"]], ["Preparados para o X", r["x_preparados"]]]
    rows += [[f"Pautas — {k}", v] for k, v in r["categorias"].items()]
    t = Table([[P(a), P(b)] for a, b in rows], colWidths=[110 * mm, 50 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9dde5")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    story += [P("Resumo executivo", h2), t]

    story.append(P("LinkedIn", h2))
    if not data["linkedin"]:
        story.append(P("Nenhuma publicação no período.", small))
    for i in data["linkedin"]:
        story += [P(i["titulo"], h3),
                  P(f"{i['categoria']} · {i['situacao']} · {_fmt(hz, i['data_hora'])}" + (f" · {i['link']}" if i["link"] else ""), small),
                  P(i["texto"])]
        if i.get("erro"):
            story.append(P(f"Ocorrência: {i['erro']}", small))
    story.append(P("X — conteúdos para publicação manual", h2))
    if not data["x"]:
        story.append(P("Nenhum conteúdo preparado no período.", small))
    for i in data["x"]:
        story += [P(i["titulo"], h3), P(f"{i['situacao']}" + (f" · {i['link']}" if i["link"] else ""), small)]
        story.append(P("\n\n".join(i["thread"]) if i["thread"] else i["texto"]))
        if i["poster"]:
            story.append(P(f"Poster autorizado: {i['poster'].get('credito')}", small))
        elif i["restricao_imagem"]:
            story.append(P(f"Imagem: {i['restricao_imagem']}", small))
        story.append(P("Fontes: " + "; ".join(f"{s['veiculo']} ({s['url']})" for s in i["fontes"]), small))

    story.append(P("Ocorrências", h2))
    oc = data["ocorrencias"]
    labels = {"publicacoes_nao_realizadas": "Publicações não realizadas", "pautas_suspensas": "Pautas suspensas",
              "noticias_descartadas": "Notícias descartadas", "restricoes_de_imagem": "Restrições de direitos de imagem",
              "falhas_de_integracao": "Falhas de integração", "problemas_tecnicos": "Problemas técnicos",
              "fontes_com_erro": "Fontes com erro"}
    for key, label in labels.items():
        items = oc.get(key) or []
        story.append(P(f"{label}: {len(items)}", h3))
        for it in items[:15]:
            story.append(P("• " + " — ".join(str(v) for v in it.values() if v), small))
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=data["titulo"], author="HORIZONTE")
    doc.build(story)
    return out.getvalue()
