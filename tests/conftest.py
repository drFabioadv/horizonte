"""Ambiente de teste: internet, Ollama e LinkedIn simulados (nada sai do computador)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs

import httpx
import pytest

NOW = datetime.now(timezone.utc)


def rfc(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


def rss(items: list[tuple]) -> bytes:
    """items: (titulo, link, horas_atras, resumo, imagem|None)"""
    body = []
    for title, link, h, summary, img in items:
        media = f'<media:content url="{img}" medium="image"/>' if img else ""
        body.append(f"<item><title>{title}</title><link>{link}</link><pubDate>{rfc(h)}</pubDate>"
                    f"<description>{summary}</description>{media}</item>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
        f"<channel><title>Teste</title>{''.join(body)}</channel></rss>"
    ).encode()


FEEDS = {
    "https://senado.test/rss": rss([
        ("Senado aprova PEC da Segurança Pública em dois turnos", "https://senado.test/n/pec-seguranca?utm_source=rss", 3,
         "O Plenário do Senado aprovou a PEC da Segurança Pública por 62 votos a 8. O texto segue para a Câmara dos Deputados.", None),
    ]),
    "https://g1.test/rss": rss([
        ("Senado aprova PEC da Segurança Pública; texto vai à Câmara", "https://g1.test/politica/pec-seguranca", 2,
         "A proposta foi aprovada por 62 votos a 8 e agora será analisada pela Câmara.", "https://img.test/g1.jpg"),
        ("PF prende suspeito de fraude em licitação em Belém", "https://g1.test/pa/pf-fraude", 4,
         "Segundo a PF, o suspeito é investigado por fraude em contratos da prefeitura.", None),
        ("Previsão do tempo hoje", "https://g1.test/tempo", 1, "Sol.", None),
    ]),
    "https://folha.test/rss": rss([
        ("Senado aprova PEC da Segurança Pública sem redução da maioridade penal", "https://folha.test/poder/pec", 2.5,
         "Foram 62 votos favoráveis e 8 contrários.", None),
        ("Enem 2026 tem 32% de abstenção no primeiro dia de prova", "https://folha.test/educacao/enem", 5,
         "O Inep informou que 32% dos inscritos faltaram ao primeiro dia do Enem 2026.", None),
        ("Ministério nega que vá cortar verbas da saúde indígena", "https://folha.test/saude/verbas", 6,
         "O ministério nega o corte; entidades contestam os números divulgados.", None),
        ("Câmara aprovou reforma administrativa em 2019", "https://folha.test/antiga", 24 * 6,
         "Notícia antiga sobre a reforma.", None),
    ]),
    "https://agbr.test/rss": rss([
        ("Enem 2026 registra abstenção de 32% no primeiro dia, informa Inep", "https://agbr.test/educacao/enem", 4,
         "Segundo o Inep, 32% dos inscritos não compareceram ao primeiro dia do Enem 2026.", "https://img.test/agbr.jpg"),
        ("STF julga validade de lei estadual sobre proteção de dados de servidores", "https://agbr.test/justica/stf-dados", 3,
         "O Supremo Tribunal Federal começou a julgar a constitucionalidade da lei estadual; o relator votou pela validade.", None),
        ("Governo nega corte em verbas da saúde indígena", "https://agbr.test/saude/verbas", 5,
         "O governo nega o corte de verbas, contestado por entidades.", None),
    ]),
    "https://conjur.test/feed": rss([
        ("STF começa a julgar lei estadual sobre proteção de dados de servidores", "https://conjur.test/stf-dados", 2,
         "O relator votou pela validade da lei estadual sobre proteção de dados de servidores públicos.", None),
    ]),
}

TEST_SOURCES = [
    ("Agência Senado (teste)", "senado", "primaria", "juridica", "https://senado.test/", "https://senado.test/rss", "politica", "BR", "nao_liberada"),
    ("G1 (teste)", "g1", "imprensa", "jornalistica", "https://g1.test/", "https://g1.test/rss", None, "BR", "nao_liberada"),
    ("Folha (teste)", "folha", "imprensa", "jornalistica", "https://folha.test/", "https://folha.test/rss", None, "BR", "nao_liberada"),
    ("Agência Brasil (teste)", "agencia-brasil", "publica", "politica", "https://agbr.test/", "https://agbr.test/rss", None, "BR", "liberada_com_credito"),
    ("Conjur (teste)", "conjur", "imprensa", "jornalistica", "https://conjur.test/", "https://conjur.test/feed", "direito", "BR", "nao_liberada"),
]


class FakeWorld:
    """Simula os serviços externos e registra as chamadas feitas."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.ollama_up = True
        self.ollama_models = ["gemma4:12b"]
        self.llm_mode = "ok"  # ok | bad_once | always_bad
        self.llm_calls = 0
        self.linkedin_mode = "ok"  # ok | 401 | 429 | 426_once | 500
        self.version_seen: list[str] = []
        self.posts_created: list[dict] = []
        self.comments: list[dict] = []
        self._426_done = False

    # ------------------------------------------------------------ IA simulada
    def _llm(self, prompt: str) -> dict:
        self.llm_calls += 1
        bad = self.llm_mode == "always_bad" or (self.llm_mode == "bad_once" and "CORRIJA" not in prompt)
        invented = " Segundo levantamento, 73% dos brasileiros apoiam a medida." if bad else ""
        if "Produza a análise" in prompt:
            return {"titulo": "Análise da pauta", "o_que_aconteceu": "O fato foi registrado pelas fontes." + invented,
                    "contexto": "Contexto institucional.", "fatos_confirmados": ["Fato confirmado pelas fontes."],
                    "informacoes_atribuidas": ["Segundo as fontes, o texto avança."], "relevancia": "Relevância pública.",
                    "analise_critica": "A decisão merece exame dos fundamentos e das consequências.",
                    "reflexao": "Que critérios devem orientar o debate?", "cautelas": ["O tema ainda pode mudar."]}
        return {"linkedin": {"texto": "Abertura sóbria sobre o fato.\n\nContexto e análise crítica fundamentada." + invented,
                             "hashtags": ["Direito", "#Política", "Instituições", "Brasil", "Cidadania", "Extra"]},
                "x": {"chamada": "Chamada curta", "texto": "O fato, com um ângulo analítico conciso." + invented,
                      "thread": [], "hashtags": ["Brasil", "Política"], "orientacao": ""}}

    # ------------------------------------------------------------ roteador
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        host = request.url.host
        if url in FEEDS:
            return httpx.Response(200, content=FEEDS[url], headers={"content-type": "application/rss+xml"})
        if host == "127.0.0.1" and request.url.port == 11434:
            if not self.ollama_up:
                raise httpx.ConnectError("recusado", request=request)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": m} for m in self.ollama_models]})
            if request.url.path == "/api/generate":
                payload = json.loads(request.content)
                return httpx.Response(200, json={"response": json.dumps(self._llm(payload["prompt"]), ensure_ascii=False)})
        if host == "img.test":
            return httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * 100, headers={"content-type": "image/jpeg"})
        if host == "www.linkedin.com" and request.url.path == "/oauth/v2/accessToken":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            return httpx.Response(200, json={"access_token": "TOKEN-SECRETO-123456", "expires_in": 5184000,
                                             "scope": "openid,profile,w_member_social"})
        if host == "www.linkedin.com" and request.url.path == "/oauth/v2/revoke":
            return httpx.Response(200)
        if host == "api.linkedin.com" and request.url.path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "abc123", "name": "Fabio Teste"})
        if host == "api.linkedin.com" and request.url.path.startswith("/rest/"):
            self.version_seen.append(request.headers.get("LinkedIn-Version"))
            assert request.headers.get("X-Restli-Protocol-Version") == "2.0.0"
            if self.linkedin_mode == "426_once" and not self._426_done:
                self._426_done = True
                return httpx.Response(426, json={"code": "NONEXISTENT_VERSION"})
            if self.linkedin_mode == "401":
                return httpx.Response(401, json={"message": "Invalid access token"})
            if self.linkedin_mode == "429":
                return httpx.Response(429, json={"message": "Too many requests"})
            if self.linkedin_mode == "500":
                return httpx.Response(500, json={"message": "erro"})
            if request.url.path == "/rest/images":
                return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin.test/up/1",
                                                           "image": "urn:li:image:IMG1"}})
            if request.url.path == "/rest/documents":
                if getattr(self, "documents_fail", False):
                    return httpx.Response(400, json={"message": "documento recusado"})
                return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin.test/doc/1",
                                                           "document": "urn:li:document:DOC1"}})
            if request.url.path.startswith("/rest/socialActions/"):
                self.comments.append(json.loads(request.content))
                return httpx.Response(201, json={})
            if request.url.path == "/rest/posts":
                body = json.loads(request.content)
                self.posts_created.append(body)
                n = len(self.posts_created)
                return httpx.Response(201, headers={"x-restli-id": f"urn:li:share:{7000 + n}"})
        if host == "upload.linkedin.test":
            return httpx.Response(201)
        return httpx.Response(404)


@pytest.fixture
def world():
    return FakeWorld()


@pytest.fixture
def hz(tmp_path, world, monkeypatch):
    monkeypatch.setenv("HORIZONTE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "cliente-teste")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "segredo-teste")
    monkeypatch.setenv("HORIZONTE_ADMIN_TOKEN", "chave-teste")
    monkeypatch.setenv("LINKEDIN_API_VERSION", "")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
    for k in ("HORIZONTE_SECRET_KEY",):
        monkeypatch.delenv(k, raising=False)
    from horizonte.config import load_settings
    from horizonte.core import Horizonte

    h = Horizonte(load_settings(), transport=httpx.MockTransport(world.handler))
    # os testes antigos usam 3 posts/dia e pôster simples; o carrossel tem teste próprio
    h.set_prefs({"linkedin_por_dia": 3, "linkedin_horarios": ["08:30", "12:30", "18:30"], "formato_linkedin": "poster"})
    with h.db.tx() as conn:
        conn.execute("DELETE FROM sources")
        for s in TEST_SOURCES:
            conn.execute(
                "INSERT INTO sources(name, org, tier, group_name, homepage, feed_url, category_hint, region, image_policy) "
                "VALUES (?,?,?,?,?,?,?,?,?)", s)
    yield h
    h.db.close()


def connect_linkedin(hz):
    from horizonte import linkedin

    url = linkedin.auth_url(hz)
    state = parse_qs(url.split("?", 1)[1])["state"][0]
    res = linkedin.handle_callback(hz, "CODIGO-DE-TESTE-1234", state)
    assert res["ok"], res
    return res
