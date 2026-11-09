"""IA local via Ollama (gratuita, roda no computador do usuário)."""
from __future__ import annotations

import json
import re

import httpx


class LLMUnavailable(RuntimeError):
    pass


def status(hz) -> dict:
    """Detecta o Ollama, lista modelos e diz se o modelo escolhido está pronto."""
    model = hz.prefs().get("ollama_modelo") or hz.settings.ollama_model
    out = {"url": hz.settings.ollama_url, "instalado": False, "modelos": [], "modelo": model, "pronto": False,
           "mensagem": ""}
    try:
        with hz.http(timeout=5) as client:
            r = client.get(f"{hz.settings.ollama_url}/api/tags")
            r.raise_for_status()
            models = [m.get("name") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        out["mensagem"] = "Ollama não encontrado. Instale em ollama.com e deixe-o aberto."
        return out
    out["instalado"] = True
    out["modelos"] = models
    if model in models or (":" not in model and f"{model}:latest" in models):
        out["pronto"] = True
        out["mensagem"] = f"Modelo {model} pronto."
    else:
        out["mensagem"] = f"O modelo {model} não está baixado. Rode no terminal: ollama pull {model}"
    return out


_THINK = re.compile(r"<think>.*?</think>", re.S)


def generate_json(hz, prompt: str, system: str, temperature: float = 0.4, timeout: float = 600) -> dict:
    """Pede uma resposta em JSON ao modelo local. Levanta LLMUnavailable se não houver IA."""
    st = status(hz)
    if not st["pronto"]:
        raise LLMUnavailable(st["mensagem"])
    payload = {
        "model": st["modelo"],
        "system": system,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    try:
        with hz.http(timeout=timeout) as client:
            r = client.post(f"{hz.settings.ollama_url}/api/generate", json=payload)
            r.raise_for_status()
            text = r.json().get("response", "")
    except httpx.HTTPError as e:
        raise LLMUnavailable(f"Falha ao falar com o Ollama: {type(e).__name__}") from e
    text = _THINK.sub("", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise ValueError("A IA local não devolveu um JSON válido.")
