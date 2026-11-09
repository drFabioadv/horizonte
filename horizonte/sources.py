"""Fontes de notícias padrão e descoberta automática de feeds RSS.

As fontes ficam no banco e podem ser editadas no painel. Os endereços abaixo
foram testados em 09/11/2026. Órgãos sem RSS público funcionando entram
desligados, com observação, e podem ser testados de novo pelo painel.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import feedparser
import httpx

# tier: primaria (o próprio órgão), publica (agência pública de notícias), imprensa
# group_name: juridica | politica | jornalistica (como no prompt mestre)
DEFAULT_SOURCES: list[dict] = [
    # ---------- jurídicas / órgãos ----------
    {"name": "STF – Notícias", "org": "stf", "tier": "primaria", "group_name": "juridica", "homepage": "https://noticias.stf.jus.br/", "feed_url": "https://noticias.stf.jus.br/feed/", "category_hint": "direito", "enabled": 0, "note": "O feed atual do STF traz páginas institucionais, não notícias. Teste de novo pelo painel."},
    {"name": "STJ – Notícias", "org": "stj", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.stj.jus.br/sites/portalp/Comunicacao/Ultimas-noticias", "feed_url": None, "category_hint": "direito", "enabled": 0, "note": "Sem RSS público encontrado."},
    {"name": "TST – Notícias", "org": "tst", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.tst.jus.br/noticias", "feed_url": None, "category_hint": "direito", "enabled": 0, "note": "Sem RSS público encontrado."},
    {"name": "CNJ – Notícias", "org": "cnj", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.cnj.jus.br/", "feed_url": None, "category_hint": "direito", "enabled": 0, "note": "Sem RSS público encontrado."},
    {"name": "Planalto – Notícias", "org": "planalto", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.gov.br/planalto/pt-br", "feed_url": "https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/noticias/RSS", "category_hint": "politica", "enabled": 1},
    {"name": "Diário Oficial da União", "org": "dou", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.in.gov.br/", "feed_url": None, "category_hint": "direito", "enabled": 0, "note": "Sem RSS público estável. Consulte o texto oficial no site da Imprensa Nacional."},
    {"name": "Agência Câmara", "org": "camara", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.camara.leg.br/noticias", "feed_url": "https://www.camara.leg.br/noticias/rss/ultimas-noticias", "category_hint": "politica", "enabled": 1},
    {"name": "Agência Senado", "org": "senado", "tier": "primaria", "group_name": "juridica", "homepage": "https://www12.senado.leg.br/noticias", "feed_url": "https://www12.senado.leg.br/noticias/feed/todasnoticias/RSS", "category_hint": "politica", "enabled": 1},
    {"name": "TCU – Notícias", "org": "tcu", "tier": "primaria", "group_name": "juridica", "homepage": "https://portal.tcu.gov.br/imprensa/noticias", "feed_url": "https://portal.tcu.gov.br/rss.xml", "category_hint": "politica", "enabled": 1},
    {"name": "TJPA", "org": "tjpa", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.tjpa.jus.br/PortalExterno/", "feed_url": None, "category_hint": "direito", "region": "PA", "enabled": 0, "note": "Site não respondeu ao teste automático; sem RSS encontrado."},
    {"name": "TRT da 8ª Região", "org": "trt8", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.trt8.jus.br/", "feed_url": None, "category_hint": "direito", "region": "PA", "enabled": 0, "note": "Site bloqueia leitura automática (403)."},
    {"name": "MPPA", "org": "mppa", "tier": "primaria", "group_name": "juridica", "homepage": "https://www2.mppa.mp.br/", "feed_url": None, "category_hint": "direito", "region": "PA", "enabled": 0, "note": "Site não respondeu ao teste automático."},
    {"name": "TCE-PA", "org": "tcepa", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.tcepa.tc.br/", "feed_url": None, "category_hint": "politica", "region": "PA", "enabled": 0, "note": "Sem RSS público encontrado."},
    {"name": "ALEPA", "org": "alepa", "tier": "primaria", "group_name": "juridica", "homepage": "https://www.alepa.pa.gov.br/", "feed_url": None, "category_hint": "politica", "region": "PA", "enabled": 0, "note": "Sem RSS público encontrado."},
    # ---------- políticas / institucionais ----------
    {"name": "Governo Federal – gov.br", "org": "govbr", "tier": "primaria", "group_name": "politica", "homepage": "https://www.gov.br/pt-br/noticias", "feed_url": "https://www.gov.br/pt-br/noticias/RSS", "category_hint": "politica", "enabled": 1},
    {"name": "Agência Brasil – Política", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml", "category_hint": "politica", "enabled": 1},
    {"name": "Agência Brasil – Justiça", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/justica/feed.xml", "category_hint": "direito", "enabled": 1},
    {"name": "Agência Brasil – Direitos Humanos", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/direitos-humanos/feed.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Agência Brasil – Geral", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Agência Brasil – Educação", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/educacao/feed.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Agência Brasil – Saúde", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/saude/feed.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Agência Brasil – Economia", "org": "agencia-brasil", "tier": "publica", "group_name": "politica", "homepage": "https://agenciabrasil.ebc.com.br/", "feed_url": "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Agência Pará", "org": "agencia-para", "tier": "primaria", "group_name": "politica", "homepage": "https://agenciapara.com.br/", "feed_url": None, "category_hint": "politica", "region": "PA", "enabled": 0, "note": "Sem RSS público encontrado."},
    # ---------- jornalísticas ----------
    {"name": "G1 – Política", "org": "g1", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://g1.globo.com/politica/", "feed_url": "https://g1.globo.com/rss/g1/politica/", "category_hint": "politica", "enabled": 1},
    {"name": "G1 – Pará", "org": "g1", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://g1.globo.com/pa/para/", "feed_url": "https://g1.globo.com/rss/g1/pa/para/", "category_hint": None, "region": "PA", "enabled": 1},
    {"name": "BBC News Brasil", "org": "bbc", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.bbc.com/portuguese", "feed_url": "https://feeds.bbci.co.uk/portuguese/rss.xml", "category_hint": None, "enabled": 1},
    {"name": "CNN Brasil", "org": "cnn", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.cnnbrasil.com.br/", "feed_url": "https://www.cnnbrasil.com.br/feed/", "category_hint": None, "enabled": 1},
    {"name": "Folha – Poder", "org": "folha", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www1.folha.uol.com.br/poder/", "feed_url": "https://feeds.folha.uol.com.br/poder/rss091.xml", "category_hint": "politica", "enabled": 1},
    {"name": "Folha – Cotidiano", "org": "folha", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www1.folha.uol.com.br/cotidiano/", "feed_url": "https://feeds.folha.uol.com.br/cotidiano/rss091.xml", "category_hint": "sociedade", "enabled": 1},
    {"name": "Estadão – Política", "org": "estadao", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.estadao.com.br/politica/", "feed_url": "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/", "category_hint": "politica", "enabled": 1},
    {"name": "O Liberal – Política", "org": "oliberal", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.oliberal.com/politica", "feed_url": "https://www.oliberal.com/cmlink/politica-oliberal-com-1.332277", "category_hint": "politica", "enabled": 1},
    {"name": "O Liberal – Pará", "org": "oliberal", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.oliberal.com/para", "feed_url": "https://www.oliberal.com/cmlink/par%C3%A1-o-liberal-com-1.332273", "category_hint": None, "region": "PA", "enabled": 1},
    {"name": "Diário do Pará", "org": "diariodopara", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://diariodopara.com.br/", "feed_url": "https://diariodopara.com.br/feed/", "category_hint": None, "enabled": 1},
    {"name": "Agência Pública", "org": "apublica", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://apublica.org/", "feed_url": "https://apublica.org/feed/", "category_hint": "sociedade", "enabled": 1},
    {"name": "Conjur", "org": "conjur", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.conjur.com.br/", "feed_url": "https://conjur.com.br/feed/", "category_hint": "direito", "enabled": 1},
    {"name": "JOTA", "org": "jota", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.jota.info/", "feed_url": "https://www.jota.info/feed", "category_hint": "direito", "enabled": 1},
    {"name": "Poder360", "org": "poder360", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.poder360.com.br/", "feed_url": "https://www.poder360.com.br/feed/", "category_hint": "politica", "enabled": 1},
    {"name": "Congresso em Foco", "org": "congressoemfoco", "tier": "imprensa", "group_name": "jornalistica", "homepage": "https://www.congressoemfoco.com.br/", "feed_url": "https://www.congressoemfoco.com.br/rss", "category_hint": "politica", "enabled": 1},
]

_COMMON_SUFFIXES = ["feed/", "rss", "rss.xml", "feed", "RSS", "feed.xml"]


def seed_sources(db) -> int:
    """Insere as fontes padrão que ainda não existem (não altera as editadas pelo usuário)."""
    added = 0
    with db.tx() as conn:
        for s in DEFAULT_SOURCES:
            cur = conn.execute(
                "INSERT OR IGNORE INTO sources(name, org, tier, group_name, homepage, feed_url, category_hint, region, enabled, note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (s["name"], s["org"], s["tier"], s["group_name"], s["homepage"], s.get("feed_url"),
                 s.get("category_hint"), s.get("region", "BR"), s.get("enabled", 1), s.get("note")),
            )
            added += cur.rowcount
    return added


def _has_entries(client: httpx.Client, url: str) -> int:
    try:
        r = client.get(url)
        if r.status_code >= 400:
            return 0
        parsed = feedparser.parse(r.content)
        return len(parsed.entries)
    except httpx.HTTPError:
        return 0


def discover_feed(client: httpx.Client, homepage: str, current: str | None = None) -> tuple[str | None, str]:
    """Procura um feed que funcione: o atual, os anunciados na página e caminhos comuns."""
    tried: list[str] = []
    if current:
        n = _has_entries(client, current)
        if n:
            return current, f"Feed atual funcionando ({n} itens)."
        tried.append(current)
    try:
        r = client.get(homepage)
        html = r.text if r.status_code < 400 else ""
        base = str(r.url)
    except httpx.HTTPError as e:
        return None, f"Página inicial não respondeu ({type(e).__name__})."
    candidates: list[str] = []
    for tag in re.findall(r"<link[^>]+>", html, flags=re.I):
        if "alternate" in tag.lower() and re.search(r"rss|atom", tag, re.I):
            m = re.search(r'href=["\']([^"\']+)', tag)
            if m:
                candidates.append(urljoin(base, m.group(1)))
    candidates += [urljoin(base, s) for s in _COMMON_SUFFIXES]
    seen = set(tried)
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        n = _has_entries(client, c)
        if n:
            return c, f"Feed encontrado ({n} itens)."
    return None, "Nenhum feed RSS público encontrado."
