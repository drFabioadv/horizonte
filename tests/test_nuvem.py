"""Publicação pela nuvem: PC envia a fila criptografada; o GitHub Actions publica; o PC marca."""
import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
from nacl import encoding, public

from conftest import connect_linkedin


class FakeGitHub:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.branches = {"main": "sha-main"}
        self.secrets: dict[str, str] = {}
        self.sk = public.PrivateKey.generate()

    def handle(self, req: httpx.Request):
        p = req.url.path
        base = "/repos/drFabioadv/horizonte"
        assert req.headers["Authorization"] in ("Bearer gh-teste", "Bearer github_pat_PAINEL123456")
        if p == base:
            return httpx.Response(200, json={"permissions": {"push": True}})
        if p.endswith("/dispatches"):
            return httpx.Response(204)
        if p == f"{base}/git/ref/heads/nuvem":
            return httpx.Response(200 if "nuvem" in self.branches else 404, json={"object": {"sha": "x"}})
        if p == f"{base}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "sha-main"}})
        if p == f"{base}/git/refs":
            self.branches["nuvem"] = "sha"
            return httpx.Response(201, json={})
        if p == f"{base}/actions/secrets/public-key":
            return httpx.Response(200, json={"key_id": "k1", "key": self.sk.public_key.encode(encoding.Base64Encoder()).decode()})
        if p.startswith(f"{base}/actions/secrets/"):
            enc = json.loads(req.content)["encrypted_value"]
            self.secrets[p.rsplit("/", 1)[1]] = public.SealedBox(self.sk).decrypt(base64.b64decode(enc)).decode()
            return httpx.Response(201)
        if p.startswith(f"{base}/contents/"):
            name = p.split("/contents/", 1)[1]
            if req.method == "GET":
                if name not in self.files:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, json={"content": base64.b64encode(self.files[name]).decode(), "sha": "s"})
            body = json.loads(req.content)
            assert body["branch"] == "nuvem"
            self.files[name] = base64.b64decode(body["content"])
            return httpx.Response(200, json={})
        return None


def _setup(hz, world, monkeypatch):
    monkeypatch.setenv("HORIZONTE_GITHUB_TOKEN", "gh-teste")
    gh = FakeGitHub()
    old = world.handler

    def handler(req):
        if req.url.host == "api.github.com":
            r = gh.handle(req)
            if r is not None:
                return r
        return old(req)

    hz.transport = httpx.MockTransport(handler)
    return gh, handler


def test_queue_roundtrip_publish_and_sync(hz, world, monkeypatch, tmp_path):
    from horizonte import linkedin, nuvem
    from horizonte.pipeline import daily_cycle

    gh, handler = _setup(hz, world, monkeypatch)
    connect_linkedin(hz)
    hz.set_prefs({"linkedin_auto": True})
    daily_cycle(hz)  # produz e já envia a fila
    assert "nuvem" in gh.branches and nuvem.SECRET_NAME in gh.secrets and "fila.enc" in gh.files
    assert b"TOKEN-SECRETO" not in gh.files["fila.enc"]  # criptografado
    # com a nuvem ativa, o PC não publica sozinho
    hz.db.execute("UPDATE posts SET scheduled_for=? WHERE network='linkedin'", ("2020-01-01T00:00:00+00:00",))
    assert linkedin.publish_due(hz).get("nuvem") and not world.posts_created
    nuvem.sync(hz)

    # --- no GitHub Actions
    pasta = tmp_path / "nuvem-dados"
    pasta.mkdir()
    (pasta / "fila.enc").write_bytes(gh.files["fila.enc"])
    key = gh.secrets[nuvem.SECRET_NAME]
    now = datetime.now(timezone.utc)
    st = nuvem.publish_cloud(pasta / "fila.enc", pasta / "publicados.json", key, now=now, transport=httpx.MockTransport(handler))
    assert st["situacao"] == "ok" and st["ultimo"].startswith("https://www.linkedin.com/feed/update/")
    assert len(world.posts_created) == 1 and world.posts_created[0]["content"]["media"]["id"] == "urn:li:image:IMG1"
    # logo depois: respeita o intervalo
    st = nuvem.publish_cloud(pasta / "fila.enc", pasta / "publicados.json", key, now=now + timedelta(minutes=10),
                             transport=httpx.MockTransport(handler))
    assert "intervalo" in st["mensagem"] and len(world.posts_created) == 1
    st = nuvem.publish_cloud(pasta / "fila.enc", pasta / "publicados.json", key, now=now + timedelta(minutes=95),
                             transport=httpx.MockTransport(handler))
    assert len(world.posts_created) == 2

    # --- de volta ao PC
    gh.files["publicados.json"] = (pasta / "publicados.json").read_bytes()
    res = nuvem.sync(hz)
    assert res["marcados"] == 2
    assert hz.db.scalar("SELECT COUNT(*) FROM posts WHERE network='linkedin' AND status='publicado'") == 2
    assert nuvem.status(hz)["status_nuvem"]["situacao"] == "ok"


def test_cloud_wrong_key_and_expired(tmp_path):
    from cryptography.fernet import Fernet

    from horizonte import nuvem

    k = Fernet.generate_key()
    q = {"token": {"access_token": "t", "sub": "s", "scopes": [], "expires_at": "2020-01-01T00:00:00+00:00"}, "itens": []}
    (tmp_path / "fila.enc").write_bytes(Fernet(k).encrypt(json.dumps(q).encode()))
    st = nuvem.publish_cloud(tmp_path / "fila.enc", tmp_path / "p.json", Fernet.generate_key().decode())
    assert st["situacao"] == "erro" and "chave" in st["mensagem"]
    st = nuvem.publish_cloud(tmp_path / "fila.enc", tmp_path / "p.json", k.decode())
    assert "venceu" in st["mensagem"]


def test_evening_cycle_produces_for_tomorrow(hz, world):
    from horizonte import scheduler

    now = hz.local_now().replace(hour=21, minute=0)
    fired = scheduler.tick(hz, now)
    assert "ciclo_amanha" in fired
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    rows = hz.db.query("SELECT p.scheduled_for FROM posts p JOIN stories s ON s.id=p.story_id WHERE p.network='linkedin'")
    assert rows and all(s["day"] == tomorrow for s in hz.db.query("SELECT day FROM stories"))
    local = [datetime.fromisoformat(r["scheduled_for"]).astimezone(hz.tz).strftime("%H:%M") for r in rows]
    assert sorted(local) == ["08:30", "12:30", "18:30"]


def test_token_pasted_in_panel(hz, world, monkeypatch):
    from horizonte import nuvem

    gh, _ = _setup(hz, world, monkeypatch)
    monkeypatch.delenv("HORIZONTE_GITHUB_TOKEN")
    assert not nuvem.configured(hz)
    assert not nuvem.save_token(hz, "abc")["ok"]
    connect_linkedin(hz)
    hz.set_prefs({"linkedin_auto": True})
    res = nuvem.save_token(hz, "github_pat_PAINEL123456")
    assert res["ok"] and nuvem.configured(hz) and "fila.enc" in gh.files
    raw = hz.db.scalar("SELECT data FROM tokens WHERE provider='github'")
    assert "github_pat" not in raw  # guardado criptografado
    assert nuvem.dispatch(hz)["ok"]
