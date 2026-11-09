"""Funções de texto: normalização, tokens, URLs canônicas e números."""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STOPWORDS = set(
    """a o os as um uma uns umas de do da dos das no na nos nas em por para pra com sem sobre entre ate após apos
    e ou mas que se ao aos à às pelo pela pelos pelas seu sua seus suas ele ela eles elas isso este esta esse essa
    diz dizem afirma após apos ser foi sao são está esta estao estão tem têm ter vai vão mais menos muito nova novo
    contra como quando onde ja já nao não sim ainda tambem também ha há sera será diante durante""".split()
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def fold(text: str) -> str:
    """Minúsculas e sem acentos, para comparação."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def norm_title(title: str) -> str:
    return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]", " ", fold(title))).strip()


def tokens(text: str) -> set[str]:
    return {w for w in norm_title(text).split() if len(w) >= 3 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a: set[str], b: set[str]) -> float:
    """Proporção do menor conjunto que aparece no maior (títulos curtos x longos)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|at_|cmpid|origin|from|ref$)", re.I)


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit(("https", host, path, urlencode(query), ""))


_NUM_RE = re.compile(r"(?<![\w])(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(\d+))?\s*(%|mil\b|milh(?:ão|ões|oes|ao)\b|bilh(?:ão|ões|oes|ao)\b)?", re.I)


def numbers(text: str) -> set[str]:
    """Números relevantes de um texto, normalizados (ex.: '1.200' -> '1200', '3,5%' -> '3,5')."""
    found = set()
    for m in _NUM_RE.finditer(text or ""):
        whole = re.sub(r"[.\s]", "", m.group(1))
        value = whole + ("," + m.group(2) if m.group(2) else "")
        if len(whole) == 1 and not m.group(2) and not m.group(3):
            continue  # números de um dígito soltos ("2 pontos") são comuns e pouco arriscados
        found.add(value)
    return found


def quotes(text: str) -> list[str]:
    """Trechos entre aspas com tamanho de citação."""
    out = []
    for m in re.finditer(r"[“\"]([^”\"]{18,})[”\"]", text or ""):
        out.append(m.group(1).strip())
    return out


def x_length(text: str) -> int:
    """Tamanho no X: links contam 23 caracteres."""
    return len(re.sub(r"https?://\S+", "x" * 23, text))
