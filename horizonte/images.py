"""Material visual: só oferece imagem para republicar quando há autorização clara."""
from __future__ import annotations

from pathlib import Path

POLICIES = {
    "nao_liberada": "Sem autorização clara de reuso",
    "liberada_com_credito": "Reuso permitido com crédito (confirmado pelo usuário para esta fonte)",
}


def pick_image(items: list[dict]) -> dict | None:
    """Escolhe a imagem de uma pauta. Itens trazem image_url, image_policy, source_name e url."""
    restricted = None
    for it in items:
        if not it.get("image_url"):
            continue
        if it.get("image_policy") == "liberada_com_credito":
            return {
                "url": it["image_url"],
                "autorizada": True,
                "credito": f"Foto: {it['source_name']}",
                "origem": it["url"],
                "observacao": POLICIES["liberada_com_credito"],
            }
        if restricted is None:
            restricted = {
                "url": None,
                "autorizada": False,
                "credito": None,
                "origem": it["url"],
                "observacao": (
                    f"A imagem de {it['source_name']} não tem autorização clara de reuso. "
                    "Use o link da publicação original ou envie uma imagem sua."
                ),
            }
    return restricted


def user_image(path: Path, original_name: str) -> dict:
    return {
        "url": f"/uploads/{path.name}",
        "arquivo": str(path),
        "autorizada": True,
        "credito": "Material fornecido pelo usuário",
        "origem": None,
        "observacao": f"Enviada pelo usuário ({original_name}).",
    }
