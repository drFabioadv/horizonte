"""Integração oficial com o LinkedIn (OAuth 2.0 + Posts API), sem automação de navegador.

Requisitos gratuitos (self-serve): um app no LinkedIn Developers com os produtos
"Share on LinkedIn" (w_member_social) e "Sign In with LinkedIn using OpenID
Connect" (openid, profile). O token dura cerca de 60 dias e apps self-serve não
recebem refresh token: quando vencer, é preciso reconectar pelo painel.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .db import loads, now_iso, utcnow
from .verify import VERIFICADA, verify_cluster

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
INTERVALO_MIN = 90  # mínimo entre dois posts automáticos
IMAGES_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
SCOPES = "openid profile w_member_social"
PROVIDER = "linkedin"


class LinkedInError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retry: bool = False, reconnect: bool = False):
        super().__init__(message)
        self.status = status
        self.retry = retry
        self.reconnect = reconnect


# ---------------------------------------------------------------- token


def configured(hz) -> bool:
    return bool(hz.settings.linkedin_client_id and hz.settings.linkedin_client_secret)


def _load_token(hz) -> dict | None:
    row = hz.db.one("SELECT data FROM tokens WHERE provider=?", (PROVIDER,))
    return hz.vault.decrypt(row["data"]) if row else None


def _save_token(hz, data: dict) -> None:
    hz.db.execute(
        "INSERT INTO tokens(provider, data, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(provider) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (PROVIDER, hz.vault.encrypt(data), now_iso()),
    )


def _valid_token(hz) -> dict | None:
    tok = _load_token(hz)
    if not tok or tok.get("invalido"):
        return None
    if datetime.fromisoformat(tok["expires_at"]) <= utcnow() + timedelta(minutes=5):
        return None
    return tok


def status(hz) -> dict:
    prefs = hz.prefs()
    out = {"configurado": configured(hz), "conectado": False, "nome": None, "expira_em": None,
           "dias_restantes": None, "permissoes": [], "pode_publicar": False, "modo_auto": bool(prefs["linkedin_auto"]),
           "versao_api": api_version(hz), "redirect_uri": hz.settings.linkedin_redirect_uri, "mensagem": ""}
    if not out["configurado"]:
        out["mensagem"] = "Preencha LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET no arquivo .env (veja o README)."
        return out
    tok = _load_token(hz)
    if not tok:
        out["mensagem"] = "Conta não conectada."
        return out
    exp = datetime.fromisoformat(tok["expires_at"])
    out.update({"nome": tok.get("name"), "expira_em": tok["expires_at"], "permissoes": tok.get("scopes", []),
                "dias_restantes": max(0, (exp - utcnow()).days)})
    if tok.get("invalido"):
        out["mensagem"] = "O LinkedIn recusou o token. Reconecte a conta."
    elif exp <= utcnow():
        out["mensagem"] = "A autorização venceu (o LinkedIn não renova sozinha). Reconecte a conta."
    else:
        out["conectado"] = True
        out["pode_publicar"] = "w_member_social" in tok.get("scopes", [])
        out["mensagem"] = "Conectado." if out["pode_publicar"] else "Conectado, mas sem a permissão w_member_social."
        if out["dias_restantes"] is not None and out["dias_restantes"] <= 7:
            out["mensagem"] += f" A autorização vence em {out['dias_restantes']} dia(s)."
    return out


def auth_url(hz) -> str:
    state = secrets.token_urlsafe(24)
    hz.db.execute("INSERT INTO oauth_states(state, created_at) VALUES (?,?)", (state, now_iso()))
    params = {"response_type": "code", "client_id": hz.settings.linkedin_client_id,
              "redirect_uri": hz.settings.linkedin_redirect_uri, "state": state, "scope": SCOPES}
    return f"{AUTH_URL}?{urlencode(params)}"


def handle_callback(hz, code: str | None, state: str | None, error: str | None = None) -> dict:
    if error:
        return {"ok": False, "mensagem": f"O LinkedIn não autorizou: {error}"}
    row = hz.db.one("SELECT created_at FROM oauth_states WHERE state=?", (state or "",))
    hz.db.execute("DELETE FROM oauth_states WHERE state=? OR created_at < ?",
                  (state or "", (utcnow() - timedelta(minutes=15)).isoformat(timespec="seconds")))
    if not row or datetime.fromisoformat(row["created_at"]) < utcnow() - timedelta(minutes=15):
        return {"ok": False, "mensagem": "Pedido de conexão expirado ou inválido. Tente conectar de novo."}
    if not code:
        return {"ok": False, "mensagem": "O LinkedIn não devolveu o código de autorização."}
    with hz.http(timeout=20) as client:
        r = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": hz.settings.linkedin_redirect_uri,
            "client_id": hz.settings.linkedin_client_id, "client_secret": hz.settings.linkedin_client_secret,
        })
        if r.status_code != 200:
            hz.log("error", "linkedin", f"Troca do código falhou: HTTP {r.status_code} {r.text[:200]}")
            return {"ok": False, "mensagem": f"O LinkedIn recusou a troca do código (HTTP {r.status_code})."}
        tok = r.json()
        access = tok["access_token"]
        scopes = [s for s in re.split(r"[ ,]+", tok.get("scope", "")) if s]
        u = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
        if u.status_code != 200:
            return {"ok": False, "mensagem": "Não foi possível ler o perfil (confira o produto OpenID Connect no app)."}
        info = u.json()
    expires_at = (utcnow() + timedelta(seconds=int(tok.get("expires_in", 5184000)))).isoformat(timespec="seconds")
    _save_token(hz, {"access_token": access, "expires_at": expires_at, "scopes": scopes or SCOPES.split(),
                     "sub": info.get("sub"), "name": info.get("name"), "connected_at": now_iso()})
    hz.log("info", "linkedin", f"Conta conectada: {info.get('name')}. Permissões: {', '.join(scopes)}")
    return {"ok": True, "mensagem": f"Conta de {info.get('name')} conectada."}


def disconnect(hz) -> dict:
    tok = _load_token(hz)
    if tok and configured(hz):
        try:
            with hz.http(timeout=15) as client:
                client.post(REVOKE_URL, data={"client_id": hz.settings.linkedin_client_id,
                                              "client_secret": hz.settings.linkedin_client_secret,
                                              "token": tok["access_token"]})
        except httpx.HTTPError:
            pass
    hz.db.execute("DELETE FROM tokens WHERE provider=?", (PROVIDER,))
    hz.set_prefs({"linkedin_auto": False})
    hz.log("info", "linkedin", "Conta desconectada e modo automático desligado.")
    return {"ok": True}


# ---------------------------------------------------------------- versão da API


def _month_back(yyyymm: str, n: int) -> str:
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    m -= n
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}{m:02d}"


def api_version(hz) -> str:
    if hz.settings.linkedin_version:
        return hz.settings.linkedin_version
    stored = hz.db.get_pref("linkedin_api_version_ok")
    if stored:
        return stored
    today = date.today()
    return _month_back(f"{today.year}{today.month:02d}", 2)


def _rest(hz, client: httpx.Client, method: str, url: str, token: str, **kw) -> httpx.Response:
    """Chamada /rest com o cabeçalho de versão; se a versão foi aposentada (426), recua mês a mês."""
    version = api_version(hz)
    extra = kw.pop("headers", {})
    for _ in range(8):
        headers = {"Authorization": f"Bearer {token}", "LinkedIn-Version": version,
                   "X-Restli-Protocol-Version": "2.0.0", **extra}
        r = client.request(method, url, headers=headers, **kw)
        if r.status_code == 426 or (r.status_code == 400 and "VERSION" in r.text.upper() and "NONEXISTENT" in r.text.upper()):
            version = _month_back(version, 1)
            continue
        if r.status_code < 400 and not hz.settings.linkedin_version:
            hz.db.set_pref("linkedin_api_version_ok", version)
        return r
    return r


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    body = r.text[:300]
    if r.status_code == 401:
        raise LinkedInError("Token recusado pelo LinkedIn (401). Reconecte a conta.", 401, reconnect=True)
    if r.status_code == 403:
        raise LinkedInError(f"Sem permissão para publicar (403). Confira o produto Share on LinkedIn. {body}", 403)
    if r.status_code == 429:
        raise LinkedInError("Limite de chamadas do LinkedIn atingido (429). Nova tentativa mais tarde.", 429, retry=True)
    if r.status_code >= 500:
        raise LinkedInError(f"Instabilidade no LinkedIn (HTTP {r.status_code}).", r.status_code, retry=True)
    raise LinkedInError(f"O LinkedIn recusou a publicação (HTTP {r.status_code}): {body}", r.status_code)


# ---------------------------------------------------------------- texto (little text format)

_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<![\w#])#([\wÀ-ÿ]+)")


def to_little_text(text: str) -> str:
    """Escapa caracteres reservados do formato do LinkedIn e transforma #tags em hashtags reais."""
    tags: list[str] = []

    def keep(m):
        tags.append(m.group(1))
        return f"\x00{len(tags) - 1}\x00"

    tmp = _HASHTAG.sub(keep, text)
    tmp = _RESERVED.sub(r"\\\1", tmp)
    return re.sub(r"\x00(\d+)\x00", lambda m: "{hashtag|\\#|" + tags[int(m.group(1))] + "}", tmp)


# ---------------------------------------------------------------- imagem


def _image_bytes(hz, client: httpx.Client, image: dict) -> tuple[bytes, str] | None:
    if image.get("arquivo"):
        p = Path(image["arquivo"])
        if not p.exists():
            return None
        data = p.read_bytes()
        ctype = {".png": "image/png", ".gif": "image/gif"}.get(p.suffix.lower(), "image/jpeg")
        return data, ctype
    if image.get("url", "").startswith("http"):
        r = client.get(image["url"])
        ctype = r.headers.get("content-type", "").split(";")[0]
        if r.status_code == 200 and ctype in ("image/jpeg", "image/png", "image/gif"):
            return r.content, ctype
    return None


def upload_image(hz, client: httpx.Client, token: str, owner: str, image: dict) -> str | None:
    got = _image_bytes(hz, client, image)
    if not got:
        return None
    data, ctype = got
    r = _rest(hz, client, "POST", IMAGES_URL, token, json={"initializeUploadRequest": {"owner": owner}})
    _raise_for(r)
    value = r.json()["value"]
    up = client.put(value["uploadUrl"], content=data, headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    if up.status_code >= 400:
        raise LinkedInError(f"Falha ao enviar a imagem (HTTP {up.status_code}).", up.status_code, retry=up.status_code >= 500)
    return value["image"]


# ---------------------------------------------------------------- publicação


def _create_post(hz, client: httpx.Client, tok: dict, text: str, visibility: str, image: dict | None,
                 alt: str) -> tuple[str, str]:
    author = f"urn:li:person:{tok['sub']}"
    body = {
        "author": author,
        "commentary": to_little_text(text),
        "visibility": visibility,
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image and image.get("autorizada"):
        urn = upload_image(hz, client, tok["access_token"], author, image)
        if urn:
            body["content"] = {"media": {"id": urn, "altText": alt[:120]}}
    r = _rest(hz, client, "POST", POSTS_URL, tok["access_token"], json=body,
              headers={"Content-Type": "application/json"})
    _raise_for(r)
    post_urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or ""
    if not post_urn:
        raise LinkedInError("O LinkedIn aceitou o pedido, mas não informou o identificador do post.", r.status_code)
    return post_urn, f"https://www.linkedin.com/feed/update/{post_urn}/"


def publish_post(hz, post_id: int, force: bool = False) -> dict:
    """Publica um post do LinkedIn. force=True ignora o horário (botão 'publicar agora')."""
    post = hz.db.one("SELECT * FROM posts WHERE id=? AND network='linkedin'", (post_id,))
    if not post:
        return {"ok": False, "mensagem": "Post não encontrado."}
    post = dict(post)
    if post["status"] == "publicado":
        return {"ok": True, "mensagem": "Já publicado.", "url": post["external_url"]}
    if post["status"] in ("publicando", "verificar"):
        return {"ok": False, "mensagem": "Este post já teve uma tentativa interrompida. Confira no LinkedIn antes de republicar."}
    tok = _valid_token(hz)
    if not tok:
        return {"ok": False, "mensagem": "LinkedIn não conectado ou autorização vencida."}
    if "w_member_social" not in tok.get("scopes", []):
        return {"ok": False, "mensagem": "A autorização não inclui a permissão w_member_social."}
    if post["story_id"]:
        story = hz.db.one("SELECT cluster_id FROM stories WHERE id=?", (post["story_id"],))
        check = verify_cluster(hz, story["cluster_id"]) if story else {"status": VERIFICADA}
        if check.get("status") != VERIFICADA:
            reason = f"Suspenso: a verificação da pauta mudou para {check.get('status')}."
            hz.db.execute("UPDATE posts SET status='suspenso', error=?, updated_at=? WHERE id=?", (reason, now_iso(), post_id))
            return {"ok": False, "mensagem": reason}
    already = hz.db.scalar(
        "SELECT 1 FROM posts WHERE network='linkedin' AND status='publicado' AND content_hash=? AND id<>?",
        (post["content_hash"], post_id),
    )
    if already:
        hz.db.execute("UPDATE posts SET status='suspenso', error=?, updated_at=? WHERE id=?",
                      ("Conteúdo idêntico já publicado.", now_iso(), post_id))
        return {"ok": False, "mensagem": "Conteúdo idêntico já publicado."}

    with hz.db.tx() as conn:
        cur = conn.execute("UPDATE posts SET status='publicando', updated_at=? WHERE id=? AND status IN ('agendado','falhou')",
                           (now_iso(), post_id))
        if not cur.rowcount:
            return {"ok": False, "mensagem": "O post mudou de estado; atualize a página."}
    visibility = hz.prefs().get("linkedin_visibilidade", "PUBLIC")
    try:
        with hz.http(timeout=40) as client:
            urn, url = _create_post(hz, client, tok, post["body"], visibility, loads(post["image"], None),
                                    post["title"] or "")
    except LinkedInError as e:
        if e.reconnect:
            tok["invalido"] = True
            _save_token(hz, tok)
        if e.retry:
            later = (utcnow() + timedelta(minutes=30)).isoformat(timespec="seconds")
            hz.db.execute("UPDATE posts SET status='agendado', scheduled_for=?, error=?, updated_at=? WHERE id=?",
                          (later, str(e), now_iso(), post_id))
        else:
            hz.db.execute("UPDATE posts SET status='falhou', error=?, updated_at=? WHERE id=?", (str(e), now_iso(), post_id))
        hz.log("error", "linkedin", f"Post {post_id}: {e}")
        from .notify import notify

        notify(hz, "HORIZONTE — falha no LinkedIn", str(e)[:180])
        return {"ok": False, "mensagem": str(e)}
    except httpx.HTTPError as e:
        hz.db.execute("UPDATE posts SET status='verificar', error=?, updated_at=? WHERE id=?",
                      (f"Conexão caiu durante a publicação ({type(e).__name__}). Confira no LinkedIn antes de republicar.",
                       now_iso(), post_id))
        hz.log("error", "linkedin", f"Post {post_id}: conexão caiu durante a publicação.")
        return {"ok": False, "mensagem": "A conexão caiu durante a publicação. Confira no LinkedIn."}
    hz.db.execute(
        "UPDATE posts SET status='publicado', published_at=?, external_id=?, external_url=?, error=NULL, updated_at=? WHERE id=?",
        (now_iso(), urn, url, now_iso(), post_id),
    )
    if post["story_id"]:
        hz.db.execute("UPDATE stories SET status='publicada', updated_at=? WHERE id=?", (now_iso(), post["story_id"]))
        hz.db.execute("INSERT INTO story_events(story_id, ts, event, detail) VALUES (?,?,?,?)",
                      (post["story_id"], now_iso(), "publicada_linkedin", url))
    hz.log("info", "linkedin", f"Publicado no LinkedIn: {url}")
    return {"ok": True, "url": url, "id": urn}


def publish_test(hz) -> dict:
    """Publicação de teste, visível só para conexões, para confirmar a integração."""
    text = (f"Teste de integração do HORIZONTE — Direito. Política. Sociedade. "
            f"({hz.local_now().strftime('%d/%m/%Y %H:%M')}). Esta publicação pode ser apagada.")
    tok = _valid_token(hz)
    if not tok:
        return {"ok": False, "mensagem": "LinkedIn não conectado ou autorização vencida."}
    try:
        with hz.http(timeout=30) as client:
            urn, url = _create_post(hz, client, tok, text, "CONNECTIONS", None, "")
    except (LinkedInError, httpx.HTTPError) as e:
        hz.log("error", "linkedin", f"Teste falhou: {e}")
        return {"ok": False, "mensagem": str(e)}
    from .editorial import content_hash

    hz.db.execute(
        "INSERT OR IGNORE INTO posts(network, format, title, body, status, published_at, external_id, external_url, "
        "content_hash, created_at, updated_at) VALUES ('linkedin','post','Publicação de teste',?,'publicado',?,?,?,?,?,?)",
        (text, now_iso(), urn, url, content_hash("linkedin", text), now_iso(), now_iso()),
    )
    hz.log("info", "linkedin", f"Publicação de teste feita: {url}")
    return {"ok": True, "url": url}


def publish_due(hz) -> dict:
    """Publica os posts cujo horário chegou, se o modo automático estiver ligado."""
    prefs = hz.prefs()
    out = {"publicados": 0, "falhas": 0, "aguardando": 0}
    if prefs["pausado"]:
        return out
    due = hz.db.query(
        "SELECT id FROM posts WHERE network='linkedin' AND status='agendado' AND scheduled_for<=? ORDER BY scheduled_for",
        (now_iso(),),
    )
    if not due:
        return out
    if not prefs["linkedin_auto"] or not _valid_token(hz):
        out["aguardando"] = len(due)
        return out
    # Se o PC ficou desligado e vários horários passaram, não "despeja" tudo de uma vez:
    # publica um por vez, com pelo menos INTERVALO_MIN minutos entre um post e outro.
    last = hz.db.one("SELECT MAX(published_at) AS t FROM posts WHERE network='linkedin' AND status='publicado'")
    if last and last["t"]:
        from datetime import datetime, timedelta, timezone

        try:
            when = datetime.fromisoformat(last["t"].replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - when < timedelta(minutes=INTERVALO_MIN):
                out["aguardando"] = len(due)
                return out
        except ValueError:
            pass
    res = publish_post(hz, due[0]["id"])
    out["publicados" if res.get("ok") else "falhas"] += 1
    out["aguardando"] = len(due) - 1
    return out


def recover_interrupted(hz) -> int:
    """Na inicialização: posts que estavam 'publicando' quando o PC desligou não são repetidos às cegas."""
    cur = hz.db.execute(
        "UPDATE posts SET status='verificar', error=?, updated_at=? WHERE network='linkedin' AND status='publicando'",
        ("Interrompido durante a publicação. Confira no LinkedIn se saiu; depois marque como publicado ou tente de novo.",
         now_iso()),
    )
    return cur.rowcount


def resolve_post(hz, post_id: int, action: str, url: str | None = None) -> dict:
    """Resolve manualmente um post que ficou em 'verificar', 'falhou' ou 'suspenso'."""
    post = hz.db.one("SELECT status FROM posts WHERE id=? AND network='linkedin'", (post_id,))
    if not post:
        return {"ok": False, "mensagem": "Post não encontrado."}
    if action == "marcar_publicado":
        hz.db.execute("UPDATE posts SET status='publicado', published_at=?, external_url=COALESCE(?, external_url), "
                      "error=NULL, updated_at=? WHERE id=?", (now_iso(), url or None, now_iso(), post_id))
    elif action == "tentar_de_novo":
        hz.db.execute("UPDATE posts SET status='agendado', scheduled_for=?, error=NULL, updated_at=? WHERE id=?",
                      (now_iso(), now_iso(), post_id))
    elif action == "cancelar":
        hz.db.execute("UPDATE posts SET status='cancelado', updated_at=? WHERE id=?", (now_iso(), post_id))
    else:
        return {"ok": False, "mensagem": "Ação desconhecida."}
    hz.log("info", "linkedin", f"Post {post_id}: ação manual '{action}'.")
    return {"ok": True}
