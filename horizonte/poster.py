"""Pôsteres de opinião com a identidade do autor (não do HORIZONTE).

Visual de coluna de opinião: papel claro, a OPINIÃO em destaque, a notícia como contexto
("Sobre:") e a assinatura do autor com monograma, nome e registro profissional.
Formato 1080x1350 (4:5), o que o LinkedIn mostra maior no feed. Sem foto de terceiros.
Fontes tipográficas livres (Lora e Poppins, SIL Open Font License) vêm junto.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
M = 96  # margem lateral
FONTS = Path(__file__).parent / "assets" / "fonts"

TEMAS = {
    "claro": {"bg": (243, 238, 229), "ink": (24, 24, 27), "muted": (104, 100, 94), "line": (206, 198, 186)},
    "escuro": {"bg": (21, 23, 28), "ink": (240, 236, 228), "muted": (150, 150, 158), "line": (60, 62, 70)},
}
ACENTO = {  # uma cor por editoria, como seções de um jornal
    "direito": (122, 31, 43),     # bordô
    "politica": (30, 58, 95),     # azul-tinta
    "sociedade": (47, 93, 80),    # verde-oliva
    None: (122, 31, 43),
}
ACENTO_ESCURO = {"direito": (214, 120, 120), "politica": (130, 168, 214), "sociedade": (120, 190, 160), None: (214, 120, 120)}
CATEGORIAS = {"direito": "DIREITO", "politica": "POLÍTICA", "sociedade": "SOCIEDADE"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_PARTICULAS = {"da", "de", "do", "das", "dos", "e"}


def _font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except (OSError, AttributeError):
            pass
    return f


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for w in para.split():
            test = f"{cur} {w}".strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return [l for l in lines if l] or [""]


def _fit(draw, text: str, name: str, sizes, width: int, max_lines: int, weight=None):
    """Maior fonte em que o texto cabe no número de linhas; senão corta com reticências."""
    font, lines = None, []
    for size in sizes:
        font = _font(name, size, weight)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines:
            return font, lines
    lines = lines[:max_lines]
    while lines and draw.textlength(lines[-1] + "…", font=font) > width:
        lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
    lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return font, lines


def _data_pt(iso: str | None) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else datetime.now()
    except ValueError:
        dt = datetime.now()
    return f"{dt.day:02d} {MESES[dt.month - 1]} {dt.year}"


def iniciais(nome: str) -> str:
    partes = [p for p in re.split(r"\s+", nome.strip()) if p and p.lower() not in _PARTICULAS]
    return "".join(p[0].upper() for p in partes[:2]) or "•"


def autor_de(prefs: dict) -> dict:
    return {
        "nome": str(prefs.get("autor_nome") or "").strip(),
        "titulo": str(prefs.get("autor_titulo") or "").strip(),
        "tema": prefs.get("poster_tema") if prefs.get("poster_tema") in TEMAS else "claro",
    }


def _signature(img: Image.Image, autor: dict, acento, tema: dict, y: int) -> None:
    """Assinatura do autor: monograma num círculo, nome e registro profissional."""
    d = ImageDraw.Draw(img)
    nome, titulo = autor.get("nome") or "", autor.get("titulo") or ""
    if not nome:
        return
    r = 44
    cx, cy = M + r, y + r
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acento, width=3)
    mono = iniciais(nome)
    fm = _font("Lora-Variable.ttf", 38, 700)
    tw = d.textlength(mono, font=fm)
    bbox = d.textbbox((0, 0), mono, font=fm)
    d.text((cx - tw / 2, cy - (bbox[3] + bbox[1]) / 2), mono, font=fm, fill=acento)
    x = M + 2 * r + 26
    d.text((x, y + (6 if titulo else 26)), nome, font=_font("Poppins-Bold.ttf", 30), fill=tema["ink"])
    if titulo:
        d.text((x, y + 50), titulo, font=_font("Poppins-Regular.ttf", 23), fill=tema["muted"])


def frase_da_analise(analysis: dict, limite: int = 200) -> str:
    """Frase do pôster quando a IA não trouxe uma: a tese, ou o começo da análise."""
    for key in ("tese", "analise_critica", "reflexao", "relevancia"):
        txt = str(analysis.get(key) or "").strip()
        if txt:
            if len(txt) > limite:
                acc = ""
                for s in re.split(r"(?<=[.!?])\s", txt):
                    if len(acc) + len(s) + 1 > limite:
                        break
                    acc = f"{acc} {s}".strip()
                txt = acc or txt[:limite].rsplit(" ", 1)[0] + "…"
            return txt
    return ""


def render_news(titulo: str, frase: str, categoria: str | None, fontes: list[str], data_iso: str | None,
                autor: dict | None = None) -> Image.Image:
    autor = autor or {}
    tema = TEMAS[autor.get("tema") or "claro"]
    escuro = autor.get("tema") == "escuro"
    acento = (ACENTO_ESCURO if escuro else ACENTO).get(categoria, ACENTO[None])
    img = Image.new("RGB", (W, H), tema["bg"])
    d = ImageDraw.Draw(img)
    width = W - 2 * M
    d.rectangle([0, 0, W, 14], fill=acento)  # faixa de cor da editoria

    # cabeçalho: OPINIÃO · EDITORIA ............ data
    y = 92
    fl = _font("Poppins-Bold.ttf", 22)
    label = f"OPINIÃO  ·  {CATEGORIAS.get(categoria or '', 'ANÁLISE')}"
    d.text((M, y), label, font=fl, fill=acento)
    dt = _data_pt(data_iso)
    fd = _font("Poppins-Regular.ttf", 22)
    d.text((W - M - d.textlength(dt, font=fd), y), dt, font=fd, fill=tema["muted"])
    d.line([(M, y + 50), (W - M, y + 50)], fill=tema["line"], width=2)

    # a opinião é o destaque
    sig_top = H - 200
    area_top = y + 120
    sobre_h = 0
    if titulo:
        fs, sl = _fit(d, "Sobre: " + titulo, "Poppins-Regular.ttf", range(26, 20, -2), width, 3)
        sobre_h = int(fs.size * 1.45) * len(sl) + 70
    room = sig_top - 70 - sobre_h - area_top
    frase = frase or titulo
    fq, ql = None, []
    for size in range(78, 40, -4):
        lh = int(size * 1.22)
        fq, ql = _fit(d, frase, "Lora-Variable.ttf", range(size, size - 1, -1), width, max(2, room // lh), weight=600)
        if not ql[-1].endswith("…"):
            break
    lh = int(fq.size * 1.22)
    block = lh * len(ql) + sobre_h
    yq = area_top + max(0, (sig_top - 70 - area_top - block) // 2 - 20)
    for line in ql:
        d.text((M, yq), line, font=fq, fill=tema["ink"])
        yq += lh
    if titulo:
        yq += 34
        d.line([(M, yq), (M + 90, yq)], fill=acento, width=5)
        yq += 34
        for line in sl:
            d.text((M, yq), line, font=fs, fill=tema["muted"])
            yq += int(fs.size * 1.45)

    # rodapé: fontes (miúdo) e assinatura
    d.line([(M, sig_top - 34), (W - M, sig_top - 34)], fill=tema["line"], width=2)
    _signature(img, autor, acento, tema, sig_top)
    if fontes:
        txt = "Fontes: " + ", ".join(dict.fromkeys(fontes))
        ff, fls = _fit(d, txt, "Poppins-Regular.ttf", range(19, 15, -2), width, 1)
        d.text((M, H - 52), fls[0], font=ff, fill=tema["muted"])
    return img


def render_free(frase: str, autor: dict | None = None, categoria: str | None = None) -> Image.Image:
    autor = autor or {}
    if isinstance(autor, str):
        autor = {"nome": autor}
    tema = TEMAS[autor.get("tema") or "claro"]
    acento = (ACENTO_ESCURO if autor.get("tema") == "escuro" else ACENTO).get(categoria, ACENTO[None])
    img = Image.new("RGB", (W, H), tema["bg"])
    d = ImageDraw.Draw(img)
    width = W - 2 * M
    d.rectangle([0, 0, W, 14], fill=acento)
    sig_top = H - 200
    fq, lines = _fit(d, frase, "Lora-Variable.ttf", range(88, 40, -4), width, 9, weight=600)
    lh = int(fq.size * 1.24)
    block = lh * len(lines)
    y = max(200, (sig_top - 60 - block) // 2 + 40)
    d.text((M - 6, y - int(fq.size * 1.5)), "“", font=_font("Lora-Variable.ttf", int(fq.size * 2), 700), fill=acento)
    for line in lines:
        d.text((M, y), line, font=fq, fill=tema["ink"])
        y += lh
    d.line([(M, sig_top - 34), (W - M, sig_top - 34)], fill=tema["line"], width=2)
    _signature(img, autor, acento, tema, sig_top)
    return img


def save(hz, img: Image.Image, nome: str) -> Path:
    path = hz.settings.data_dir / "uploads" / f"{nome}-{int(time.time())}.png"
    img.save(path, "PNG", optimize=True)
    return path


def image_entry(path: Path, observacao: str, credito: str = "Arte própria") -> dict:
    return {
        "url": f"/uploads/{path.name}",
        "arquivo": str(path),
        "autorizada": True,
        "credito": credito,
        "origem": None,
        "poster": True,
        "observacao": observacao,
    }


def for_post(hz, post: dict, analysis: dict, frase: str | None = None) -> dict:
    """Gera o pôster de um post (LinkedIn) e devolve o registro de imagem pronto para anexar."""
    from .db import loads

    fontes = [s.get("veiculo") or s.get("fonte") or "" for s in loads(post.get("sources"), [])]
    frase = (frase or "").strip() or str(analysis.get("poster_frase") or "").strip() or frase_da_analise(analysis)
    autor = autor_de(hz.prefs())
    img = render_news(analysis.get("titulo") or post.get("title") or "", frase, post.get("category"),
                      [f for f in fontes if f], post.get("news_date"), autor)
    path = save(hz, img, f"poster-{post['id']}")
    return image_entry(path, "Pôster de opinião com a sua assinatura (sem foto de terceiros).",
                       f"Arte: {autor['nome']}" if autor["nome"] else "Arte própria")
