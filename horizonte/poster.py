"""Pôsteres do HORIZONTE: arte tipográfica própria (sem foto de terceiros) para os posts.

Formato 1080x1350 (4:5), o que o LinkedIn mostra maior no feed. Duas variações:
- pôster de notícia: editoria, título, comentário crítico e fontes;
- pôster livre: uma frase sua, com assinatura.
As fontes tipográficas (Lora e Poppins) são livres (SIL Open Font License) e vêm junto.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
M = 90  # margem lateral
FONTS = Path(__file__).parent / "assets" / "fonts"

NAVY_TOP = (11, 16, 32)
NAVY_BOT = (20, 30, 58)
GOLD = (226, 178, 92)
WHITE = (244, 240, 230)
MUTED = (160, 168, 190)

CATEGORIAS = {"direito": "DIREITO", "politica": "POLÍTICA", "sociedade": "SOCIEDADE"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


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
        words, cur = para.split(), ""
        for w in words:
            test = f"{cur} {w}".strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return [l for l in lines if l] or [""]


def _fit(draw, text: str, name: str, sizes: range, width: int, max_lines: int, weight=None):
    """Maior tamanho de fonte em que o texto cabe no número de linhas; senão corta com reticências."""
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


def _background() -> Image.Image:
    img = Image.new("RGB", (W, H), NAVY_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOT)))
    # sol nascendo no horizonte, discreto, no rodapé
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    cx, cy = W // 2, H - 150
    for r, a in ((330, 7), (240, 10), (170, 13)):
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD + (a,))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img)
    d.arc([cx - 115, cy - 115, cx + 115, cy + 115], 180, 360, fill=GOLD, width=5)
    d.rectangle([0, cy, W, H], fill=NAVY_BOT)
    d.line([(M, cy), (W - M, cy)], fill=WHITE, width=2)
    return img


def _brand(d: ImageDraw.ImageDraw) -> None:
    # marca no topo: arco + nome
    d.arc([M, 78, M + 56, 134], 180, 360, fill=GOLD, width=4)
    d.line([(M - 4, 106), (M + 60, 106)], fill=WHITE, width=2)
    d.text((M + 78, 86), "HORIZONTE", font=_font("Poppins-Medium.ttf", 26), fill=WHITE, spacing=0)
    # rodapé
    foot = "Direito. Política. Sociedade."
    f = _font("Poppins-Regular.ttf", 24)
    d.text(((W - d.textlength(foot, font=f)) / 2, H - 100), foot, font=f, fill=MUTED)


def _data_pt(iso: str | None) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else datetime.now()
    except ValueError:
        dt = datetime.now()
    return f"{dt.day:02d} {MESES[dt.month - 1]} {dt.year}"


def frase_da_analise(analysis: dict, limite: int = 230) -> str:
    """Comentário do pôster quando a IA não trouxe um: a reflexão ou o começo da análise crítica."""
    for key in ("reflexao", "analise_critica", "relevancia"):
        txt = str(analysis.get(key) or "").strip()
        if txt:
            if len(txt) > limite:
                cut = re.split(r"(?<=[.!?])\s", txt)
                acc = ""
                for s in cut:
                    if len(acc) + len(s) + 1 > limite:
                        break
                    acc = f"{acc} {s}".strip()
                txt = acc or txt[:limite].rsplit(" ", 1)[0] + "…"
            return txt
    return ""


def render_news(titulo: str, frase: str, categoria: str | None, fontes: list[str], data_iso: str | None) -> Image.Image:
    img = _background()
    _brand(ImageDraw.Draw(img))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # conteúdo numa camada, para centralizar se sobrar espaço
    d = ImageDraw.Draw(layer)
    width = W - 2 * M
    y = 200
    # editoria + data
    label = CATEGORIAS.get(categoria or "", "ANÁLISE")
    fl = _font("Poppins-Bold.ttf", 24)
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle([M, y, M + lw + 36, y + 46], radius=23, outline=GOLD, width=2)
    d.text((M + 18, y + 8), label, font=fl, fill=GOLD)
    d.text((M + lw + 60, y + 9), _data_pt(data_iso), font=_font("Poppins-Regular.ttf", 24), fill=MUTED)
    y += 90
    # título
    ft, lines = _fit(d, titulo, "Lora-Variable.ttf", range(66, 42, -4), width, 5, weight=700)
    lh = int(ft.size * 1.22)
    for line in lines:
        d.text((M, y), line, font=ft, fill=WHITE)
        y += lh
    y += 30
    d.line([(M, y), (M + 120, y)], fill=GOLD, width=4)
    y += 44
    # comentário
    if frase:
        room = (H - 380) - y
        for size in range(42, 28, -2):
            fq, ql = _fit(d, frase, "Lora-Italic-Variable.ttf", range(size, size - 1, -1), width - 30,
                          max(2, room // int(size * 1.38)), weight=500)
            if not ql[-1].endswith("…"):
                break
        qh = int(fq.size * 1.38)
        d.text((M - 6, y - 26), "“", font=_font("Lora-Variable.ttf", 90, 700), fill=GOLD)
        for line in ql:
            d.text((M + 30, y + 14), line, font=fq, fill=WHITE)
            y += qh
    gap = (H - 400) - y
    shift = gap // 2 - 40 if gap > 200 else 0
    img.paste(layer, (0, max(0, shift)), layer)
    d = ImageDraw.Draw(img)
    # fontes
    if fontes:
        txt = "Fontes: " + ", ".join(dict.fromkeys(fontes))
        ff, fls = _fit(d, txt, "Poppins-Regular.ttf", range(24, 18, -2), width, 2)
        fy = H - 365
        for line in fls:
            d.text((M, fy), line, font=ff, fill=MUTED)
            fy += int(ff.size * 1.4)
    return img


def render_free(frase: str, autor: str = "") -> Image.Image:
    img = _background()
    d = ImageDraw.Draw(img)
    _brand(d)
    width = W - 2 * M
    fq, lines = _fit(d, frase, "Lora-Variable.ttf", range(76, 38, -4), width, 8, weight=600)
    lh = int(fq.size * 1.3)
    block = lh * len(lines) + (80 if autor else 0)
    y = max(220, (H - 380 - block) // 2 + 100)
    d.text((M - 8, y - 110), "“", font=_font("Lora-Variable.ttf", 150, 700), fill=GOLD)
    for line in lines:
        d.text((M, y), line, font=fq, fill=WHITE)
        y += lh
    if autor:
        y += 30
        d.line([(M, y + 18), (M + 60, y + 18)], fill=GOLD, width=3)
        d.text((M + 80, y), autor, font=_font("Poppins-Medium.ttf", 30), fill=GOLD)
    return img


def save(hz, img: Image.Image, nome: str) -> Path:
    path = hz.settings.data_dir / "uploads" / f"{nome}-{int(time.time())}.png"
    img.save(path, "PNG", optimize=True)
    return path


def image_entry(path: Path, observacao: str) -> dict:
    return {
        "url": f"/uploads/{path.name}",
        "arquivo": str(path),
        "autorizada": True,
        "credito": "Arte: HORIZONTE",
        "origem": None,
        "poster": True,
        "observacao": observacao,
    }


def for_post(hz, post: dict, analysis: dict, frase: str | None = None) -> dict:
    """Gera o pôster de um post (LinkedIn) e devolve o registro de imagem pronto para anexar."""
    from .db import loads

    fontes = [s.get("veiculo") or s.get("fonte") or "" for s in loads(post.get("sources"), [])]
    frase = (frase or "").strip() or str(analysis.get("poster_frase") or "").strip() or frase_da_analise(analysis)
    img = render_news(post.get("title") or analysis.get("titulo") or "", frase, post.get("category"),
                      [f for f in fontes if f], post.get("news_date"))
    path = save(hz, img, f"poster-{post['id']}")
    return image_entry(path, "Pôster tipográfico gerado pelo HORIZONTE (sem foto de terceiros).")
