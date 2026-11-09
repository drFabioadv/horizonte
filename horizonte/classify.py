"""Classificação editorial: categoria, região, relevância e alertas de risco.

Regras transparentes por palavras-chave (funcionam sem IA). A IA local pode
refinar a análise depois, mas a triagem não depende dela.
"""
from __future__ import annotations

import re

from .textutil import fold, tokens

CATEGORY_TERMS: dict[str, list[str]] = {
    "direito": [
        "stf", "stj", "tst", "tse", "cnj", "tribunal", "ministro do supremo", "supremo", "justica", "juiz", "juiza",
        "decisao", "julgamento", "julga", "liminar", "sentenca", "acordao", "jurisprudencia", "precedente",
        "constitucional", "inconstitucional", "adi ", "adpf", "habeas corpus", "recurso", "processo", "acao judicial",
        "codigo penal", "codigo civil", "cpc", "clt", "trabalhista", "direito", "advogado", "advocacia", "oab",
        "defensoria", "ministerio publico", "mpf", "promotor", "procurador", "lei ", "lei complementar", "decreto",
        "sancion", "vigencia", "norma", "regulamenta", "eleitoral", "concurso", "magistrat", "tjpa", "trt", "tcu",
        "improbidade", "licitac", "direitos fundamentais", "garantia", "prisao preventiva", "denuncia do mp",
    ],
    "politica": [
        "governo", "presidente", "lula", "ministro", "ministerio", "planalto", "congresso", "camara", "senado",
        "deputad", "senador", "vereador", "prefeit", "governador", "assembleia", "alepa", "partido", "eleic",
        "votacao", "aprova", "plenario", "comissao", "cpi", "pec", "projeto de lei", "medida provisoria",
        "orcamento", "emenda", "politica publica", "gestao publica", "transparencia", "fiscalizacao",
        "controladoria", "cgu", "tcu", "tce", "base aliada", "oposicao", "reforma", "arcabouco", "fiscal",
    ],
    "sociedade": [
        "educacao", "escola", "enem", "universidade", "saude", "sus", "hospital", "vacina", "seguranca publica",
        "violencia", "policia", "economia", "inflacao", "emprego", "desemprego", "salario", "renda", "pobreza",
        "desigualdade", "direitos humanos", "racismo", "indigena", "quilombola", "mulher", "lgbt", "inclusao",
        "acessibilidade", "deficiencia", "cultura", "tecnologia", "inteligencia artificial", "dados pessoais",
        "meio ambiente", "desmatamento", "clima", "cop30", "cop31", "amazonia", "saneamento", "moradia", "transporte",
        "cidadania", "liberdade de expressao", "imprensa", "crianca", "idoso", "sarampo", "dengue",
    ],
}

PARA_TERMS = [
    "para:", "no para ", "do para ", "estado do para ", "paraense", "belem", "ananindeua", "santarem", "maraba",
    "castanhal", "altamira", "paragominas", "parauapebas", "tucurui", "marajo", "alepa", "tjpa", "trt-8", "trt8",
    "tce-pa", "mppa", "governo do para", "regiao norte", "amazonia",
]

INSTITUTIONAL = [
    "stf", "stj", "supremo", "congresso", "senado", "camara", "planalto", "tcu", "cnj", "lei", "decreto",
    "julgamento", "votacao", "aprova", "sancion", "ministerio publico", "governo federal", "governo do para",
]

LOW_VALUE = [
    "bbb", "novela", "horoscopo", "receita", "futebol", "campeonato", "gol ", "loteria", "mega-sena", "megasena",
    "celebridade", "famosos", "fofoca", "reality", "paysandu", "remo ", "f1 ", "formula 1", "lanche", "dieta",
]

OPINION_MARKERS = ["opiniao", "coluna", "editorial", "artigo de opiniao", "analise:", "podcast", "audio:", "video:", "ao vivo"]

RISK_TERMS = {
    "acusacao": ["acusad", "suspeit", "investigad", "indiciad", "denunciad", "reu ", "re ", "preso", "prisao",
                  "detido", "operacao da pf", "operacao policial", "fraude", "corrupc", "propina", "desvio",
                  "lavagem", "estupro", "homicid", "assassin", "agress"],
    "proposicao": ["projeto de lei", "pl ", "pec ", "proposta de emenda", "aprova em comissao", "comissao aprova",
                    "medida provisoria", "anteprojeto", "minuta"],
    "decisao_provisoria": ["liminar", "decisao monocratica", "cautelar", "suspende", "tutela de urgencia"],
    "sensivel": ["morte", "morre", "morto", "mortos", "tragedia", "vitima", "suicid", "crianca", "menor de idade"],
    "contestacao": ["nega ", "negam", "desmente", "falso", "fake", "contesta", "rebate", "boato"],
}


_PATTERNS: dict[str, re.Pattern] = {}


def _pattern(term: str) -> re.Pattern:
    """Termo com início de palavra obrigatório; espaço final exige fim de palavra."""
    pat = _PATTERNS.get(term)
    if pat is None:
        core = re.escape(term.strip())
        tail = r"(?![a-z0-9])" if term.endswith(" ") else ""
        pat = re.compile(r"(?<![a-z0-9])" + core + tail)
        _PATTERNS[term] = pat
    return pat


def _hits(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if _pattern(t).search(text))


def classify(title: str, summary: str, source: dict) -> dict:
    t = " " + fold(title) + " "
    s = " " + fold(summary or "") + " "
    scores = {}
    for cat, terms in CATEGORY_TERMS.items():
        scores[cat] = 3 * _hits(t, terms) + _hits(s, terms)
        if source.get("category_hint") == cat:
            scores[cat] += 2
    category = max(scores, key=scores.get)
    if scores[category] == 0:
        category = source.get("category_hint") or "sociedade"

    region = "PA" if (source.get("region") == "PA" or _hits(t + s, PARA_TERMS) > 0) else "BR"

    flags = [name for name, terms in RISK_TERMS.items() if _hits(t + s, terms)]
    if any(m in t for m in OPINION_MARKERS):
        flags.append("opiniao_ou_midia")

    tier_points = {"primaria": 30, "publica": 22, "imprensa": 15}.get(source.get("tier"), 10)
    relevance = tier_points + min(30, 4 * scores.get(category, 0)) + min(20, 5 * _hits(t, INSTITUTIONAL))
    if region == "PA":
        relevance += 8
    low = _hits(t, LOW_VALUE)
    if low:
        relevance -= 40 * low
    if "opiniao_ou_midia" in flags:
        relevance -= 15
    if len(re.sub(r"\s", "", title)) < 25:
        relevance -= 5
    if len(tokens(title)) < 4:
        flags.append("titulo_curto")
        relevance -= 30
    relevance = max(0, min(100, relevance))
    return {"category": category, "scores": scores, "region": region, "flags": sorted(set(flags)),
            "relevance": relevance, "low_value": bool(low)}
