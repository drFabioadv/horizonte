"""Publicação pela nuvem (GitHub Actions, gratuito): o LinkedIn recebe os posts mesmo com o PC desligado.

Como funciona
- No PC: a IA escreve os posts (de noite, para o dia seguinte). O HORIZONTE junta os posts agendados,
  a imagem de cada um e a autorização do LinkedIn num arquivo CRIPTOGRAFADO (fila.enc) e envia para a
  branch "nuvem" do repositório. A chave fica só no seu PC e num "segredo" do GitHub (ninguém mais lê).
- Na nuvem: a cada 15 minutos, das 07:00 às 21:00 (Belém), o GitHub roda `python -m horizonte.nuvem publicar`,
  que abre a fila, publica o post cujo horário chegou e anota em publicados.json (só ids e links).
- De volta no PC: o HORIZONTE lê publicados.json e marca os posts como publicados no painel.

O repositório é público, mas a fila é ilegível sem a chave. Nada de senha sai do PC.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken

BRANCH = "nuvem"
FILA = "fila.enc"
PUBLICADOS = "publicados.json"
SECRET_NAME = "HZ_NUVEM_CHAVE"
API = "https://api.github.com"
INTERVALO_MIN = 90


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ============================================================== lado do PC
_HZ = {"ref": None}  # contexto do HORIZONTE (para ler o token guardado no cofre)


def gh_token(hz=None) -> str:
    """Token do GitHub: o colado no painel (guardado criptografado) ou o do .env."""
    hz = hz or _HZ["ref"]
    if hz is not None:
        row = hz.db.one("SELECT data FROM tokens WHERE provider='github'")
        data = hz.vault.decrypt(row["data"]) if row else None
        if data and data.get("token"):
            return data["token"]
    return os.environ.get("HORIZONTE_GITHUB_TOKEN", "").strip()


def save_token(hz, token: str) -> dict:
    """Confere o token colado no painel e guarda criptografado. Já envia a fila se der certo."""
    from .db import now_iso

    token = token.strip()
    if not token.startswith(("github_pat_", "ghp_")):
        return {"ok": False, "mensagem": "Isso não parece um token do GitHub (ele começa com github_pat_)."}
    try:
        with hz.http(timeout=20, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}) as c:
            r = c.get(f"{API}/repos/{repo()}")
            if r.status_code != 200:
                return {"ok": False, "mensagem": f"O GitHub recusou o token para o repositório {repo()} (HTTP {r.status_code}). "
                                                  "Confira se escolheu o repositório horizonte ao criar o token."}
            if not (r.json().get("permissions") or {}).get("push", True):
                return {"ok": False, "mensagem": "O token não tem permissão de escrita (Contents: Read and write)."}
            r = c.get(f"{API}/repos/{repo()}/actions/secrets/public-key")
            if r.status_code != 200:
                return {"ok": False, "mensagem": "O token não tem a permissão Secrets (Read and write). Crie de novo marcando essa permissão."}
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Sem conexão com o GitHub ({type(e).__name__})."}
    hz.db.execute("INSERT INTO tokens(provider, data, updated_at) VALUES ('github',?,?) "
                  "ON CONFLICT(provider) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                  (hz.vault.encrypt({"token": token}), now_iso()))
    _set_state(hz, segredo=None)  # regrava o segredo da fila com o token novo
    hz.log("info", "nuvem", "Token do GitHub conferido e guardado (criptografado).")
    res = sync(hz, force_push=True)
    return {"ok": res.get("ok", False), "mensagem": res.get("mensagem") or "Nuvem ligada.", **res}


def dispatch(hz) -> dict:
    """Pede ao GitHub para rodar o publicador agora (teste). Precisa da permissão Actions: Read and write."""
    try:
        with _gh(hz) as c:
            r = c.post(f"{API}/repos/{repo()}/actions/workflows/publicar-linkedin.yml/dispatches", json={"ref": "main"})
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Sem conexão com o GitHub ({type(e).__name__})."}
    if r.status_code == 204:
        return {"ok": True, "mensagem": "Pedido enviado. Em 1 ou 2 minutos a execução aparece no GitHub."}
    return {"ok": False, "mensagem": f"O GitHub não deixou rodar agora (HTTP {r.status_code}). "
                                      "Falta a permissão Actions: Read and write no token, mas a nuvem roda sozinha a cada 15 min."}


def repo() -> str:
    return os.environ.get("HORIZONTE_UPDATE_REPO", "drFabioadv/horizonte").strip()


def configured(hz) -> bool:
    _HZ["ref"] = hz
    return bool(gh_token(hz) and repo())


def active(hz) -> bool:
    prefs = hz.prefs()
    return configured(hz) and bool(prefs.get("nuvem_ativa", True)) and bool(prefs.get("linkedin_auto"))


def _key(hz) -> bytes:
    p = hz.settings.data_dir / "nuvem.key"
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
    return p.read_bytes().strip()


def _gh(hz, timeout: float = 30):
    return hz.http(timeout=timeout, headers={"Authorization": f"Bearer {gh_token(hz)}",
                                             "Accept": "application/vnd.github+json",
                                             "X-GitHub-Api-Version": "2022-11-28"})


def _state(hz) -> dict:
    return hz.db.get_pref("nuvem_estado", {}) or {}


def _set_state(hz, **kw) -> dict:
    st = {**_state(hz), **kw}
    hz.db.set_pref("nuvem_estado", st)
    return st


def _nacl():
    try:
        from nacl import encoding, public  # noqa: F401
    except ImportError:  # instala sozinho na primeira vez (pacote pequeno, gratuito)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pynacl"], timeout=300, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    from nacl import encoding, public

    return encoding, public


def ensure_secret(hz, client) -> None:
    """Guarda a chave da fila como segredo do GitHub Actions (uma vez; refaz se a chave mudar)."""
    key = _key(hz)
    digest = hashlib.sha256(key).hexdigest()[:16]
    if _state(hz).get("segredo") == digest:
        return
    r = client.get(f"{API}/repos/{repo()}/actions/secrets/public-key")
    _check(r, "ler a chave pública do repositório (o token precisa da permissão Secrets)")
    pk = r.json()
    encoding, public = _nacl()
    box = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(key)).decode()
    r = client.put(f"{API}/repos/{repo()}/actions/secrets/{SECRET_NAME}",
                   json={"encrypted_value": enc, "key_id": pk["key_id"]})
    _check(r, "gravar o segredo no GitHub")
    _set_state(hz, segredo=digest)


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        msg = r.json().get("message", "") if r.headers.get("content-type", "").startswith("application/json") else r.text[:120]
        raise RuntimeError(f"Não consegui {what}: HTTP {r.status_code} {msg}".strip())


def ensure_branch(hz, client) -> None:
    r = client.get(f"{API}/repos/{repo()}/git/ref/heads/{BRANCH}")
    if r.status_code == 200:
        return
    r = client.get(f"{API}/repos/{repo()}/git/ref/heads/main")
    _check(r, "ler a branch main")
    r = client.post(f"{API}/repos/{repo()}/git/refs", json={"ref": f"refs/heads/{BRANCH}", "sha": r.json()["object"]["sha"]})
    if r.status_code != 422:  # 422 = já existe
        _check(r, "criar a branch nuvem")


def _get_file(client, path: str) -> tuple[bytes | None, str | None]:
    r = client.get(f"{API}/repos/{repo()}/contents/{path}", params={"ref": BRANCH})
    if r.status_code == 404:
        return None, None
    _check(r, f"ler {path}")
    d = r.json()
    return base64.b64decode(d.get("content", "")), d.get("sha")


def _put_file(client, path: str, data: bytes, message: str) -> None:
    _, sha = _get_file(client, path)
    body = {"message": message, "content": base64.b64encode(data).decode(), "branch": BRANCH}
    if sha:
        body["sha"] = sha
    r = client.put(f"{API}/repos/{repo()}/contents/{path}", json=body)
    _check(r, f"enviar {path}")


def build_queue(hz) -> dict:
    from . import linkedin
    from .db import loads

    tok = linkedin._valid_token(hz)
    items = []
    for p in hz.db.query("SELECT * FROM posts WHERE network='linkedin' AND status='agendado' AND scheduled_for IS NOT NULL "
                         "ORDER BY scheduled_for"):
        img = loads(p["image"], None)
        image = None
        if img and img.get("autorizada") and img.get("arquivo") and Path(img["arquivo"]).exists():
            path = Path(img["arquivo"])
            image = {"nome": path.name, "b64": base64.b64encode(path.read_bytes()).decode()}
        items.append({"id": p["id"], "quando": p["scheduled_for"], "titulo": p["title"] or "", "texto": p["body"],
                      "hash": p["content_hash"], "imagem": image})
    return {
        "gerado_em": _utcnow().isoformat(timespec="seconds"),
        "token": {k: tok[k] for k in ("access_token", "sub", "scopes", "expires_at")} if tok else None,
        "versao_api": linkedin.api_version(hz),
        "visibilidade": hz.prefs().get("linkedin_visibilidade", "PUBLIC"),
        "intervalo_min": INTERVALO_MIN,
        "itens": items,
    }


def sync(hz, force_push: bool = False) -> dict:
    """Envia a fila (se mudou) e traz o que a nuvem publicou. Seguro chamar várias vezes."""
    if not configured(hz):
        return {"ok": False, "mensagem": "Falta o HORIZONTE_GITHUB_TOKEN no .env."}
    out = {"ok": True, "marcados": 0, "enviado": False}
    try:
        with _gh(hz) as client:
            ensure_branch(hz, client)
            out["marcados"] = _pull_published(hz, client)
            if active(hz):
                ensure_secret(hz, client)
                q = build_queue(hz)
                plain = json.dumps({k: v for k, v in q.items() if k != "gerado_em"}, sort_keys=True).encode()
                digest = hashlib.sha256(plain).hexdigest()
                if force_push or digest != _state(hz).get("fila_hash"):
                    blob = Fernet(_key(hz)).encrypt(json.dumps(q).encode())
                    _put_file(client, FILA, blob, f"fila: {len(q['itens'])} post(s) agendado(s)")
                    _set_state(hz, fila_hash=digest, enviado_em=_utcnow().isoformat(timespec="seconds"),
                               itens=len(q["itens"]))
                    out["enviado"] = True
            _set_state(hz, sincronizado_em=_utcnow().isoformat(timespec="seconds"), erro=None)
    except (httpx.HTTPError, RuntimeError) as e:
        msg = str(e) if isinstance(e, RuntimeError) else f"Sem conexão com o GitHub ({type(e).__name__})."
        _set_state(hz, erro=msg)
        hz.log("warning", "nuvem", msg)
        return {"ok": False, "mensagem": msg}
    return out


def _pull_published(hz, client) -> int:
    from .db import now_iso

    raw, _ = _get_file(client, PUBLICADOS)
    if not raw:
        return 0
    data = json.loads(raw)
    if data.get("_status"):
        _set_state(hz, status_nuvem=data["_status"])
    n = 0
    for pid, info in (data.get("posts") or {}).items():
        row = hz.db.one("SELECT id, story_id, status FROM posts WHERE id=? AND network='linkedin'", (int(pid),))
        if not row or row["status"] in ("publicado", "verificar"):
            continue
        if info.get("verificar"):
            hz.db.execute("UPDATE posts SET status='verificar', error=?, updated_at=? WHERE id=?",
                          ("A conexão caiu durante a publicação pela nuvem. Confira no LinkedIn se saiu.", now_iso(), row["id"]))
            n += 1
            continue
        hz.db.execute("UPDATE posts SET status='publicado', published_at=?, external_id=?, external_url=?, error=NULL, "
                      "updated_at=? WHERE id=?", (info.get("em"), info.get("urn"), info.get("url"), now_iso(), row["id"]))
        if row["story_id"]:
            hz.db.execute("UPDATE stories SET status='publicada', updated_at=? WHERE id=?", (now_iso(), row["story_id"]))
            hz.db.execute("INSERT INTO story_events(story_id, ts, event, detail) VALUES (?,?,?,?)",
                          (row["story_id"], now_iso(), "publicada_linkedin", f"pela nuvem: {info.get('url')}"))
        n += 1
    if n:
        hz.log("info", "nuvem", f"{n} post(s) publicado(s) pela nuvem.")
    return n


_LAST = {"t": 0.0}


def soon() -> None:
    """Pede uma sincronização na próxima volta do agendador (após editar/publicar algo)."""
    _LAST["t"] = 0.0


def maybe_sync(hz, every_seconds: int = 300) -> dict | None:
    """Chamado pelo agendador: sincroniza no máximo a cada 5 minutos."""
    if not configured(hz) or time.time() - _LAST["t"] < every_seconds:
        return None
    _LAST["t"] = time.time()
    return sync(hz)


def status(hz) -> dict:
    st = _state(hz)
    return {"configurado": configured(hz), "ativa": active(hz), "repositorio": repo(),
            "enviado_em": st.get("enviado_em"), "sincronizado_em": st.get("sincronizado_em"),
            "itens": st.get("itens"), "erro": st.get("erro"), "status_nuvem": st.get("status_nuvem"),
            "acoes_url": f"https://github.com/{repo()}/actions"}


# ============================================================== lado da nuvem
def publish_cloud(fila_path: Path, publicados_path: Path, key: str, now: datetime | None = None,
                  transport: httpx.BaseTransport | None = None) -> dict:
    """Roda no GitHub Actions: publica no máximo 1 post vencido por execução."""
    now = now or _utcnow()
    pub = json.loads(publicados_path.read_text(encoding="utf-8")) if publicados_path.exists() else {}
    pub.setdefault("posts", {})

    def done(status: str, **extra) -> dict:
        pub["_status"] = {"em": now.isoformat(timespec="seconds"), "situacao": status, **extra}
        publicados_path.write_text(json.dumps(pub, ensure_ascii=False, indent=1), encoding="utf-8")
        return pub["_status"]

    if not fila_path.exists():
        return done("sem_fila")
    try:
        q = json.loads(Fernet(key.encode()).decrypt(fila_path.read_bytes()))
    except (InvalidToken, ValueError):
        return done("erro", mensagem="Não consegui abrir a fila: a chave do GitHub não confere. Abra o HORIZONTE no PC.")
    tok = q.get("token")
    if not tok:
        return done("erro", mensagem="LinkedIn desconectado no PC.")
    if _parse(tok["expires_at"]) <= now + timedelta(minutes=5):
        return done("erro", mensagem="A autorização do LinkedIn venceu. Reconecte no painel do HORIZONTE.")
    published_ids = set(pub["posts"])
    hashes = {v.get("hash") for v in pub["posts"].values()}
    last = max((_parse(v["em"]) for v in pub["posts"].values() if v.get("em")), default=None)
    due = [i for i in q["itens"] if str(i["id"]) not in published_ids and i["hash"] not in hashes and _parse(i["quando"]) <= now]
    pendentes = len([i for i in q["itens"] if str(i["id"]) not in published_ids])
    if not due:
        return done("ok", mensagem="Nada para publicar agora.", pendentes=pendentes)
    if last and now - last < timedelta(minutes=int(q.get("intervalo_min", INTERVALO_MIN))):
        return done("ok", mensagem="Aguardando o intervalo mínimo entre posts.", pendentes=pendentes)

    item = due[0]
    import tempfile

    from . import linkedin

    class _Mini:  # o necessário para reaproveitar o código de publicação do PC
        def __init__(self):
            self.settings = type("S", (), {"linkedin_version": q.get("versao_api", "")})()
            self.db = type("D", (), {"set_pref": lambda *_: None, "get_pref": lambda *_: None})()

        def http(self, timeout: float = 40, **kw):
            return httpx.Client(timeout=timeout, transport=transport, follow_redirects=True, **kw)

    hz = _Mini()
    image = None
    if item.get("imagem"):
        tmp = Path(tempfile.mkdtemp()) / item["imagem"]["nome"]
        tmp.write_bytes(base64.b64decode(item["imagem"]["b64"]))
        image = {"arquivo": str(tmp), "autorizada": True}
    try:
        with hz.http() as client:
            urn, url = linkedin._create_post(hz, client, tok, item["texto"], q.get("visibilidade", "PUBLIC"), image,
                                             item.get("titulo", ""))
    except linkedin.LinkedInError as e:
        return done("erro", mensagem=f"Post {item['id']}: {e}", pendentes=pendentes)
    except httpx.HTTPError as e:
        # pode ter saído ou não: marca para conferência, nunca repete às cegas
        pub["posts"][str(item["id"])] = {"em": now.isoformat(timespec="seconds"), "url": None, "urn": None,
                                         "hash": item["hash"], "verificar": True}
        return done("erro", mensagem=f"Conexão caiu ao publicar o post {item['id']} ({type(e).__name__}). Confira no LinkedIn.")
    pub["posts"][str(item["id"])] = {"em": now.isoformat(timespec="seconds"), "url": url, "urn": urn, "hash": item["hash"]}
    return done("ok", mensagem=f"Publicado: {item.get('titulo', '')[:80]}", pendentes=pendentes - 1, ultimo=url)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Publicador do HORIZONTE na nuvem")
    ap.add_argument("acao", choices=["publicar"])
    ap.add_argument("--pasta", default="nuvem-dados", help="pasta com fila.enc e publicados.json (branch nuvem)")
    a = ap.parse_args(argv)
    key = os.environ.get(SECRET_NAME, "").strip()
    if not key:
        print("Segredo HZ_NUVEM_CHAVE ausente: abra o HORIZONTE no PC com o token do GitHub configurado.")
        return 0
    pasta = Path(a.pasta)
    st = publish_cloud(pasta / FILA, pasta / PUBLICADOS, key)
    print(f"[HORIZONTE nuvem] {st.get('situacao')}: {st.get('mensagem', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
