"""Segurança: criptografia de tokens, mascaramento de segredos em logs e acesso ao painel."""
from __future__ import annotations

import hmac
import json
import re

from cryptography.fernet import Fernet, InvalidToken

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/=]{8,}", re.I),
    re.compile(r"(access_token[\"'=:\s]+)[A-Za-z0-9\-\._~\+/=]{8,}", re.I),
    re.compile(r"(client_secret[\"'=:\s]+)[A-Za-z0-9\-\._~\+/=]{4,}", re.I),
    re.compile(r"(refresh_token[\"'=:\s]+)[A-Za-z0-9\-\._~\+/=]{8,}", re.I),
    re.compile(r"([?&]code=)[A-Za-z0-9\-\._~]{8,}", re.I),
]


def redact(text: str) -> str:
    """Remove tokens e segredos de qualquer texto antes de gravar em log."""
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(1) + "***", out)
    return out


class Vault:
    """Guarda dados sensíveis (tokens OAuth) criptografados com a chave do .env."""

    def __init__(self, key: str):
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, data: dict) -> str:
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, blob: str) -> dict | None:
        try:
            return json.loads(self._fernet.decrypt(blob.encode()).decode())
        except (InvalidToken, ValueError):
            return None


def token_ok(given: str | None, expected: str) -> bool:
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())
