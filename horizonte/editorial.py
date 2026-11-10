"""Seleção de pautas e produção editorial (análise + textos para LinkedIn e X).

A IA local escreve, mas não decide o que é fato: os textos passam por travas
que comparam números, citações e o estágio de projetos de lei com as fontes.
Se a trava falhar duas vezes, a pauta é suspensa com o motivo.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import llm
from .db import dumps, loads, now_iso, utcnow
from .images import pick_image
from .textutil import fold, numbers, quotes, tokens, x_length
from .verify import VERIFICADA, _idf, _weighted, verify_cluster

CATEGORY_LABEL = {"direito": "Direito e Justiça", "politica": "Política e Instituições", "sociedade": "Sociedade e Cidadania"}
MIN_SCORE = 35
X_LIMIT = 280
LINKEDIN_LIMIT = 3000

SYSTEM = """Você é o editor-chefe do HORIZONTE — Direito. Política. Sociedade.
Assinatura editorial: "Informação com contexto. Análise com responsabilidade. Opinião com fundamento."
Tom: crítico, analítico e institucional. Linguagem formal, mas acessível. Português do Brasil.

Regras inegociáveis:
- Use SOMENTE os fatos presentes no PACOTE DE FONTES. Não acrescente fatos, nomes, cargos, datas, números ou citações que não estejam no pacote.
- Não invente estatísticas, decisões judiciais, citações ou opiniões de pessoas.
- Projeto de lei, PEC ou medida provisória não é lei aprovada; investigação não é condenação; acusação não é fato comprovado.
- Distinga: fato confirmado, informação atribuída a uma fonte ("segundo..."), alegação, interpretação e opinião editorial.
- Respeite a presunção de inocência, a dignidade humana e os direitos fundamentais. Sem ataques pessoais, sem sensacionalismo.
- Sem identidade partidária: avalie decisões pelos fundamentos e consequências, com o mesmo critério para qualquer governo ou grupo.
- A opinião é a linha editorial do HORIZONTE, sempre fundamentada; nunca atribua opiniões pessoais ao dono do perfil.
- Nada de frases genéricas para encher espaço. Responda sempre em JSON válido."""

ANALYSIS_PROMPT = """PACOTE DE FONTES (única base factual permitida):
{pack}

VERIFICAÇÃO: {verification}
ALERTAS: {alerts}

Produza a análise editorial em JSON com exatamente estas chaves:
{{
  "titulo": "título informativo, sem sensacionalismo (até 110 caracteres)",
  "o_que_aconteceu": "2 a 3 frases, só com fatos do pacote",
  "contexto": "contexto institucional/jurídico/social que ajuda a entender, sem fatos novos não presentes no pacote",
  "fatos_confirmados": ["fato confirmado 1", "fato 2"],
  "informacoes_atribuidas": ["o que é atribuído a uma fonte, com 'segundo X'"],
  "relevancia": "por que importa para Direito, política ou sociedade",
  "analise_critica": "análise crítica fundamentada (3 a 5 frases), marcando o que é interpretação",
  "reflexao": "uma pergunta ou reflexão para o público",
  "cautelas": ["o que ainda não se sabe ou pode mudar"]
}}"""

ADAPT_PROMPT = """PACOTE DE FONTES:
{pack}

ANÁLISE APROVADA:
{analysis}

Adapte para as duas redes, em JSON com exatamente estas chaves:
{{
  "linkedin": {{
    "texto": "post de 900 a 1800 caracteres: abertura forte e sóbria, o que aconteceu, contexto, análise crítica fundamentada e uma reflexão final. Parágrafos curtos. Sem links e sem hashtags no texto (serão acrescentados depois).",
    "hashtags": ["3 a 5 hashtags pertinentes, sem o símbolo #"],
    "poster_frase": "comentário crítico para estampar no pôster: 1 ou 2 frases, até 200 caracteres, sobre a decisão, o direito ou o efeito social; sem números que não estejam nas fontes"
  }},
  "x": {{
    "chamada": "título curto para a central (até 80 caracteres)",
    "texto": "post de até 200 caracteres, direto, com o fato e um ângulo analítico. Sem link e sem hashtags.",
    "thread": ["se o tema exigir, 2 a 4 posts de até 260 caracteres cada; caso contrário, lista vazia"],
    "hashtags": ["1 a 3 hashtags, sem #"],
    "orientacao": "dica curta de publicação, se necessária, ou string vazia"
  }}
}}
A linguagem do LinkedIn e do X deve ser diferente: no LinkedIn, profissional e desenvolvida; no X, concisa e incisiva."""

# ---------------------------------------------------------------- seleção


def _today_stories(hz, day: str) -> list[dict]:
    return [dict(r) for r in hz.db.query("SELECT * FROM stories WHERE day=?", (day,))]


def select_stories(hz, day: str | None = None) -> dict:
    """Escolhe as pautas do dia equilibrando as três áreas e evitando temas repetidos."""
    prefs = hz.prefs()
    day = day or hz.today().isoformat()
    target = max(int(prefs["linkedin_por_dia"]), int(prefs["x_por_dia"]))
    existing = [s for s in _today_stories(hz, day) if s["status"] not in ("descartada", "suspensa")]
    need = target - len(existing)
    result = {"dia": day, "meta": target, "ja_existentes": len(existing), "selecionadas": [], "motivo": None}
    if need <= 0:
        return result

    since = (utcnow() - timedelta(hours=int(prefs["idade_maxima_horas"]))).isoformat(timespec="seconds")
    cands = [
        dict(r)
        for r in hz.db.query(
            "SELECT c.* FROM clusters c LEFT JOIN stories s ON s.cluster_id=c.id "
            "WHERE s.id IS NULL AND c.verification=? AND c.score>=? AND COALESCE(c.newest_published, c.first_seen)>=? "
            "ORDER BY c.score DESC LIMIT 200",
            (VERIFICADA, MIN_SCORE, since),
        )
    ]
    cands = [c for c in cands if "titulo_curto" not in loads(c["flags"], [])]
    idf = _idf(hz, since)
    chosen_tokens = []
    for s in existing:
        row = hz.db.one("SELECT title FROM clusters WHERE id=?", (s["cluster_id"],))
        if row:
            chosen_tokens.append(tokens(row["title"]))

    dist = prefs["distribuicao"]
    total_w = sum(dist.values()) or 1
    counts = {k: sum(1 for s in existing if s["category"] == k) for k in dist}
    picked = []
    while len(picked) < need and cands:
        planned = len(existing) + len(picked) + 1
        deficits = {k: dist[k] / total_w * planned - counts.get(k, 0) for k in dist}
        order = sorted(deficits, key=deficits.get, reverse=True)
        choice = None
        for cat in order:
            for c in cands:
                if c["category"] != cat:
                    continue
                tk = tokens(c["title"])
                if any(len(tk & t) >= 2 and _weighted(tk, t, idf) >= 0.3 for t in chosen_tokens):
                    continue
                choice = c
                break
            if choice:
                break
        if not choice:
            break
        cands.remove(choice)
        chosen_tokens.append(tokens(choice["title"]))
        counts[choice["category"]] = counts.get(choice["category"], 0) + 1
        picked.append(choice)

    now = now_iso()
    for c in picked:
        with hz.db.tx() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stories(cluster_id, day, category, status, reason, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (c["id"], day, c["category"], "selecionada",
                 f"Selecionada pela relevância ({c['score']} pontos) e pelo equilíbrio entre as áreas.", now, now),
            )
            if cur.rowcount:
                conn.execute(
                    "INSERT INTO story_events(story_id, ts, event, detail) VALUES (?,?,?,?)",
                    (cur.lastrowid, now, "selecionada", c["title"]),
                )
                result["selecionadas"].append(cur.lastrowid)
    if len(result["selecionadas"]) < need:
        result["motivo"] = (
            f"Só havia {len(result['selecionadas'])} pauta(s) verificada(s) e distinta(s) além das já escolhidas. "
            "O HORIZONTE não completa a meta com notícias sem confirmação suficiente."
        )
        hz.log("warning", "editorial", result["motivo"])
    return result


# ---------------------------------------------------------------- produção


def story_items(hz, story: dict) -> list[dict]:
    rows = hz.db.query(
        "SELECT n.*, s.name AS source_name, s.org, s.tier, s.image_policy FROM news n JOIN sources s ON s.id=n.source_id "
        "WHERE n.cluster_id=? ORDER BY CASE s.tier WHEN 'primaria' THEN 0 WHEN 'publica' THEN 1 ELSE 2 END, n.relevance DESC",
        (story["cluster_id"],),
    )
    seen_orgs, items = set(), []
    for r in rows:
        d = dict(r)
        if d["org"] in seen_orgs and len(items) >= 3:
            continue
        seen_orgs.add(d["org"])
        items.append(d)
        if len(items) >= 6:
            break
    return items


def _local_date(hz, iso: str | None) -> str:
    if not iso:
        return "data não informada"
    try:
        return datetime.fromisoformat(iso).astimezone(hz.tz).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def build_pack(hz, items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"[{i}] {it['source_name']} — {_local_date(hz, it['published_at'])}\n"
            f"Título: {it['title']}\nResumo: {it['summary'] or '(sem resumo no feed)'}\nLink: {it['url']}"
        )
    return "\n\n".join(lines)


_PROPOSAL_AS_LAW = re.compile(r"\b(nova lei|lei aprovada|virou lei|foi sancionad\w*|entra em vigor|passa a valer)\b", re.I)
_GUILT = re.compile(r"\b(culpad[oa]s?|criminos[oa]s?|corrupt[oa]s?|bandid[oa]s?|ladr(ão|ões|ona)|condenad[oa]s?)\b", re.I)
_CAMPAIGN = re.compile(r"\b(vote em|vote no|vote na|não vote|fora (bolsonaro|lula)|lula lá|mito)\b", re.I)


def check_text(text: str, pack: str, flags: list[str], year: int) -> list[str]:
    """Travas factuais: tudo que parece dado precisa estar nas fontes."""
    problems = []
    pack_nums = numbers(pack)
    allowed = {str(year), str(year - 1), str(year + 1)}
    extra = sorted(n for n in numbers(text) - pack_nums - allowed)
    if extra:
        problems.append(f"Números que não aparecem nas fontes: {', '.join(extra[:6])}.")
    fpack = fold(pack)
    for q in quotes(text):
        if fold(q)[:40] not in fpack:
            problems.append(f"Citação que não está nas fontes: “{q[:60]}”.")
    if "proposicao" in flags and _PROPOSAL_AS_LAW.search(text) and "sancion" not in fpack:
        problems.append("O texto trata proposição como lei aprovada ou em vigor.")
    guilt = _GUILT.search(text)
    if guilt and "condenad" not in fpack:
        problems.append(f"O texto afirma culpa ('{guilt.group(0)}') sem condenação nas fontes.")
    if _CAMPAIGN.search(text):
        problems.append("O texto tem linguagem de campanha partidária.")
    return problems


def _flatten(analysis: dict) -> str:
    parts = []
    for v in analysis.values():
        parts.extend(v if isinstance(v, list) else [str(v)])
    return "\n".join(str(p) for p in parts)


def _clean_tags(tags, limit: int) -> list[str]:
    out = []
    for t in tags or []:
        t = re.sub(r"[^\wÀ-ÿ]", "", str(t).lstrip("#"))
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:limit]


def content_hash(network: str, text: str) -> str:
    return hashlib.sha256(f"{network}|{fold(text)}".encode()).hexdigest()


def _event(hz, story_id: int, event: str, detail: str = "") -> None:
    hz.db.execute("INSERT INTO story_events(story_id, ts, event, detail) VALUES (?,?,?,?)",
                  (story_id, now_iso(), event, detail))


def _set_story(hz, story_id: int, status: str, reason: str | None = None, analysis: dict | None = None) -> None:
    hz.db.execute(
        "UPDATE stories SET status=?, reason=COALESCE(?, reason), analysis=COALESCE(?, analysis), updated_at=? WHERE id=?",
        (status, reason, dumps(analysis) if analysis is not None else None, now_iso(), story_id),
    )
    _event(hz, story_id, status, reason or "")


def _ask_checked(hz, prompt: str, pack: str, flags: list[str], extract) -> tuple[dict | None, list[str]]:
    """Pede à IA e confere; uma segunda tentativa recebe a lista de problemas."""
    year = hz.today().year
    problems: list[str] = []
    for attempt in range(2):
        full = prompt if not problems else prompt + "\n\nCORRIJA estes problemas da versão anterior:\n- " + "\n- ".join(problems)
        data = llm.generate_json(hz, full, SYSTEM, temperature=0.35 if attempt == 0 else 0.2)
        problems = check_text(extract(data), pack, flags, year)
        if not problems:
            return data, []
    return None, problems


def next_linkedin_slot(hz, day: str) -> str:
    prefs = hz.prefs()
    tz = hz.tz
    taken = {
        r["scheduled_for"]
        for r in hz.db.query("SELECT scheduled_for FROM posts WHERE network='linkedin' AND scheduled_for IS NOT NULL")
    }
    now = hz.local_now()
    y, m, d = (int(x) for x in day.split("-"))
    for hhmm in sorted(prefs["linkedin_horarios"]):
        h, mi = (int(x) for x in hhmm.split(":"))
        slot = datetime(y, m, d, h, mi, tzinfo=tz)
        iso = slot.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
        if slot >= now and iso not in taken:
            return iso
    k = 1
    while True:  # horários do dia já passaram: espaça a partir de agora
        slot = (now + timedelta(minutes=20 * k)).replace(second=0, microsecond=0)
        iso = slot.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
        if iso not in taken:
            return iso
        k += 1


def _sources_list(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for it in items:
        if it["org"] in seen:
            continue
        seen.add(it["org"])
        out.append({"veiculo": it["source_name"], "titulo": it["title"], "url": it["url"],
                    "data": it["published_at"], "tipo": it["tier"]})
    return out[:4]


def compose_linkedin(text: str, sources: list[dict], tags: list[str], prefs: dict) -> str:
    body = text.strip()
    src = "\n".join(f"• {s['veiculo']}: {s['url']}" for s in sources)
    out = f"{body}\n\nFontes consultadas:\n{src}"
    if tags:
        out += "\n\n" + " ".join("#" + t for t in tags)
    if prefs.get("assinatura"):
        out += f"\n\n{prefs['assinatura']}"
    if prefs.get("rodape_ia"):
        out += "\nConteúdo produzido com apoio de inteligência artificial e verificado por fontes."
    return out[:LINKEDIN_LIMIT]


def compose_x(x: dict, sources: list[dict]) -> tuple[str, list[str]]:
    link = sources[0]["url"] if sources else ""
    tags = " ".join("#" + t for t in _clean_tags(x.get("hashtags"), 3))
    single = " ".join(p for p in [x.get("texto", "").strip(), link, tags] if p)
    thread = [t.strip() for t in (x.get("thread") or []) if str(t).strip()]
    if thread:
        thread = [t if x_length(t) <= X_LIMIT else t[: X_LIMIT - 1] + "…" for t in thread]
        tail = " ".join(p for p in [link, tags] if p)
        if x_length(thread[-1] + " " + tail) <= X_LIMIT:
            thread[-1] = thread[-1] + " " + tail
        else:
            thread.append(tail)
    return single, thread


def produce_story(hz, story_id: int) -> dict:
    story = dict(hz.db.one("SELECT * FROM stories WHERE id=?", (story_id,)))
    cluster = dict(hz.db.one("SELECT * FROM clusters WHERE id=?", (story["cluster_id"],)))
    check = verify_cluster(hz, cluster["id"])
    if check.get("status") != VERIFICADA:
        _set_story(hz, story_id, "suspensa", f"A verificação mudou para {check.get('status')}: " + " ".join(check.get("notes", [])[-2:]))
        return {"ok": False, "motivo": "verificação mudou"}
    items = story_items(hz, story)
    pack = build_pack(hz, items)
    flags = loads(cluster["flags"], [])
    hz.db.execute("UPDATE stories SET status='em_producao', attempts=attempts+1, updated_at=? WHERE id=?", (now_iso(), story_id))
    _event(hz, story_id, "em_producao", "Produzindo análise com a IA local.")
    try:
        analysis, problems = _ask_checked(
            hz,
            ANALYSIS_PROMPT.format(pack=pack, verification=" ".join(loads(cluster["verification_notes"], [])),
                                   alerts=", ".join(flags) or "nenhum"),
            pack, flags, _flatten,
        )
        if analysis is None:
            _set_story(hz, story_id, "suspensa", "A análise não passou nas travas factuais: " + " ".join(problems))
            return {"ok": False, "motivo": "travas", "problemas": problems}
        adapted, problems = _ask_checked(
            hz,
            ADAPT_PROMPT.format(pack=pack, analysis=dumps(analysis)),
            pack, flags,
            lambda d: "\n".join([str(d.get("linkedin", {}).get("texto", "")), str(d.get("linkedin", {}).get("poster_frase", "")),
                                 str(d.get("x", {}).get("texto", "")),
                                 *[str(t) for t in d.get("x", {}).get("thread", []) or []]]),
        )
        if adapted is None:
            _set_story(hz, story_id, "suspensa", "Os textos das redes não passaram nas travas factuais: " + " ".join(problems))
            return {"ok": False, "motivo": "travas", "problemas": problems}
    except llm.LLMUnavailable as e:
        hz.db.execute("UPDATE stories SET attempts=MAX(0, attempts-1) WHERE id=?", (story_id,))
        _set_story(hz, story_id, "aguardando_ia", f"IA local indisponível: {e}")
        return {"ok": False, "motivo": "sem_ia"}
    except ValueError as e:
        _set_story(hz, story_id, "suspensa", str(e))
        return {"ok": False, "motivo": "json"}

    prefs = hz.prefs()
    sources = _sources_list(items)
    image = pick_image(items)
    li = adapted.get("linkedin", {})
    x = adapted.get("x", {})
    li_tags = _clean_tags(li.get("hashtags"), 5)
    li_body = compose_linkedin(str(li.get("texto", "")), sources, li_tags, prefs)
    x_single, x_thread = compose_x(x, sources)
    if not x_thread and x_length(x_single) > X_LIMIT:
        x_thread = [str(x.get("texto", ""))[:X_LIMIT - 2] + "…", " ".join(p for p in [sources[0]["url"] if sources else "", " ".join("#" + t for t in _clean_tags(x.get("hashtags"), 3))] if p)]
    title = str(analysis.get("titulo") or cluster["title"])[:140]
    now = now_iso()
    news_date = cluster["newest_published"]
    created = []
    with hz.db.tx() as conn:
        li_status = "agendado"
        cur = conn.execute(
            "INSERT OR IGNORE INTO posts(story_id, network, format, title, body, hashtags, sources, image, category, news_date, "
            "status, scheduled_for, content_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (story_id, "linkedin", "post", title, li_body, dumps(li_tags), dumps(sources),
             dumps(image if image and image.get("autorizada") else None), story["category"], news_date, li_status,
             next_linkedin_slot(hz, story["day"]), content_hash("linkedin", li_body), now, now),
        )
        if cur.rowcount:
            created.append(cur.lastrowid)
        cur = conn.execute(
            "INSERT OR IGNORE INTO posts(story_id, network, format, title, body, thread, hashtags, sources, image, category, "
            "news_date, status, error, content_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (story_id, "x", "thread" if x_thread else "post", str(x.get("chamada") or title)[:120], x_single,
             dumps(x_thread), dumps(_clean_tags(x.get("hashtags"), 3)), dumps(sources), dumps(image), story["category"],
             news_date, "pronto", str(x.get("orientacao") or "") or None, content_hash("x", x_single), now, now),
        )
        if cur.rowcount:
            created.append(cur.lastrowid)
    poster_frase = str(li.get("poster_frase") or "").strip()[:260]
    if poster_frase:
        analysis["poster_frase"] = poster_frase
    _set_story(hz, story_id, "pronta", "Análise e textos aprovados nas travas factuais.", analysis)
    if prefs.get("poster_auto", True):
        attach_poster(hz, story_id, analysis)
    hz.log("info", "editorial", f"Pauta {story_id} pronta: {title}")
    return {"ok": True, "posts": created, "titulo": title}


def attach_poster(hz, story_id: int, analysis: dict | None = None, frase: str | None = None) -> dict | None:
    """Gera o pôster da pauta e anexa ao post do LinkedIn ainda não publicado (substitui imagem anterior)."""
    from . import poster

    row = hz.db.one("SELECT * FROM posts WHERE story_id=? AND network='linkedin' AND status IN ('agendado','falhou','suspenso')", (story_id,))
    if not row:
        return None
    if analysis is None:
        st = hz.db.one("SELECT analysis FROM stories WHERE id=?", (story_id,))
        analysis = loads(st["analysis"], {}) if st else {}
    try:
        img = poster.for_post(hz, dict(row), analysis or {}, frase)
    except Exception as e:  # pôster nunca derruba a produção
        hz.log("warn", "poster", f"Não foi possível gerar o pôster da pauta {story_id}: {type(e).__name__}: {e}")
        return None
    hz.db.execute("UPDATE posts SET image=?, updated_at=? WHERE id=?", (dumps(img), now_iso(), row["id"]))
    _event(hz, story_id, "poster", "Pôster gerado e anexado ao post do LinkedIn.")
    return img


def produce_pending(hz, day: str | None = None) -> dict:
    day = day or hz.today().isoformat()
    rows = hz.db.query(
        "SELECT id FROM stories WHERE day=? AND status IN ('selecionada','aguardando_ia') AND attempts < 3 ORDER BY id",
        (day,),
    )
    out = {"produzidas": 0, "falhas": 0, "sem_ia": False}
    for r in rows:
        res = produce_story(hz, r["id"])
        if res.get("ok"):
            out["produzidas"] += 1
        else:
            out["falhas"] += 1
            if res.get("motivo") == "sem_ia":
                out["sem_ia"] = True
                break  # sem IA, não adianta insistir nas outras agora
    return out
