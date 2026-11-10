"""Configuração do HORIZONTE.

Lê o arquivo .env (sem dependências externas) e define caminhos e padrões.
As preferências editáveis pelo painel ficam no banco (tabela settings);
aqui ficam apenas segredos e parâmetros de infraestrutura.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Carrega pares CHAVE=valor do .env sem sobrescrever variáveis já definidas."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Settings:
    data_dir: Path
    db_path: Path
    host: str
    port: int
    public_url: str
    timezone: str
    secret_key: str
    admin_token: str
    linkedin_client_id: str
    linkedin_client_secret: str
    linkedin_redirect_uri: str
    linkedin_version: str
    ollama_url: str
    ollama_model: str
    user_agent: str
    generated: list[str] = field(default_factory=list)


def _persisted_secret(data_dir: Path, name: str, factory) -> tuple[str, bool]:
    """Lê um segredo salvo em data/ ou cria um novo (usado quando o .env não define)."""
    path = data_dir / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip(), False
    value = factory()
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value, True


def load_settings() -> Settings:
    _load_env_file(BASE_DIR / ".env")
    data_dir = Path(os.environ.get("HORIZONTE_DATA_DIR", BASE_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)
    (data_dir / "relatorios").mkdir(exist_ok=True)

    generated: list[str] = []
    secret_key = os.environ.get("HORIZONTE_SECRET_KEY", "").strip()
    if not secret_key:
        from cryptography.fernet import Fernet

        secret_key, created = _persisted_secret(data_dir, "secret.key", lambda: Fernet.generate_key().decode())
        if created:
            generated.append("secret.key")
    admin_token = os.environ.get("HORIZONTE_ADMIN_TOKEN", "").strip()
    if not admin_token:
        admin_token, created = _persisted_secret(data_dir, "admin.token", lambda: secrets.token_urlsafe(18))
        if created:
            generated.append("admin.token")

    host = os.environ.get("HORIZONTE_HOST", "127.0.0.1")
    port = int(os.environ.get("HORIZONTE_PORT", "8787"))
    public_url = os.environ.get("HORIZONTE_PUBLIC_URL", f"http://localhost:{port}").rstrip("/")
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "horizonte.db",
        host=host,
        port=port,
        public_url=public_url,
        timezone=os.environ.get("HORIZONTE_TIMEZONE", "America/Belem"),
        secret_key=secret_key,
        admin_token=admin_token,
        linkedin_client_id=os.environ.get("LINKEDIN_CLIENT_ID", "").strip(),
        linkedin_client_secret=os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip(),
        linkedin_redirect_uri=os.environ.get(
            "LINKEDIN_REDIRECT_URI", f"{public_url}/api/linkedin/callback"
        ).strip(),
        linkedin_version=os.environ.get("LINKEDIN_API_VERSION", "").strip(),
        ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "gemma4:12b").strip(),
        user_agent=os.environ.get(
            "HORIZONTE_USER_AGENT",
            "Mozilla/5.0 (compatible; HorizonteBot/1.0; leitor RSS de uso pessoal)",
        ),
        generated=generated,
    )


# Preferências padrão editáveis no painel (gravadas na tabela settings).
DEFAULT_PREFS: dict = {
    "pausado": False,
    "linkedin_auto": False,
    "linkedin_por_dia": 3,
    "linkedin_horarios": ["08:30", "12:30", "18:30"],
    "linkedin_visibilidade": "PUBLIC",
    "x_por_dia": 3,
    "horario_ciclo": "06:30",
    "horario_relatorio": "22:00",
    "radar_intervalo_min": 60,
    "idade_maxima_horas": 48,
    "distribuicao": {"direito": 34, "politica": 33, "sociedade": 33},
    "assinatura": "",
    "autor_nome": "Fabio Garcia da Cruz",
    "autor_titulo": "Advogado · OAB/PA 44.094",
    "autor_perfil": "advogado em Belém (PA), pós-graduando em Direito Público; escreve sobre Direito, política e sociedade",
    "poster_tema": "claro",
    "rodape_ia": False,
    "ollama_modelo": "",
    "notificacoes_windows": True,
    "poster_auto": True,
    "nuvem_ativa": True,
    "producao_vespera": True,
    "horario_producao_vespera": "20:30",
}
