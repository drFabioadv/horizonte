import io
import json
import zipfile

import httpx

from conftest import connect_linkedin


def test_poster_news_and_free(hz, tmp_path):
    from horizonte import poster

    img = poster.render_news("Senado aprova PEC da Segurança Pública em dois turnos", "A aprovação desloca o debate para a Câmara.",
                             "politica", ["Agência Senado", "G1"], "2026-11-09T12:00:00Z")
    assert img.size == (1080, 1350)
    long = poster.render_news("T " * 200, "frase " * 200, None, ["X"] * 30, None)
    assert long.size == (1080, 1350)
    path = poster.save(hz, poster.render_free("Eu não sei tudo, mas sei aprender.", "Fabio"), "livre")
    assert path.exists() and path.read_bytes()[:4] == b"\x89PNG"


def test_cycle_attaches_poster_and_publishes_it(hz, world):
    from horizonte.pipeline import daily_cycle

    connect_linkedin(hz)
    daily_cycle(hz)
    post = hz.db.one("SELECT * FROM posts WHERE network='linkedin' AND status='agendado'")
    img = json.loads(post["image"])
    assert img["poster"] and img["autorizada"] and img["arquivo"].endswith(".png")
    from horizonte import linkedin

    res = linkedin.publish_post(hz, post["id"], force=True)
    assert res["ok"], res
    assert any(r.url.host == "upload.linkedin.test" for r in world.calls)
    assert world.posts_created[-1]["content"]["media"]["id"] == "urn:li:image:IMG1"


def test_poster_endpoints(hz):
    from fastapi.testclient import TestClient
    from horizonte.app import create_app
    from horizonte.pipeline import daily_cycle

    daily_cycle(hz)
    c = TestClient(create_app(hz))
    h = {"X-Horizonte-Token": "chave-teste"}
    r = c.post("/api/poster/livre", json={"frase": "Uma frase."}, headers=h)
    assert r.status_code == 200 and c.get(r.json()["url"], headers=h).content[:4] == b"\x89PNG"
    sid = hz.db.one("SELECT story_id FROM posts WHERE network='linkedin' AND status='agendado'")["story_id"]
    r = c.post(f"/api/pautas/{sid}/poster", json={"frase": "Comentário meu."}, headers=h)
    assert r.status_code == 200 and r.json()["imagem"]["poster"]


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr("horizonte-abc123/" + name, data)
    return buf.getvalue()


def test_updater_applies_without_touching_user_files(hz, tmp_path, world):
    from horizonte import updater

    target = tmp_path / "app"
    (target / "horizonte").mkdir(parents=True)
    (target / "horizonte" / "a.py").write_text("velho")
    (target / ".env").write_text("SEGREDO=meu")
    (target / "requirements.txt").write_text("fastapi\n")
    payload = _zip({"horizonte/a.py": "novo", "horizonte/b.py": "b", ".env": "SEGREDO=do-repo",
                    "data/horizonte.db": "x", "requirements.txt": "fastapi\n"})
    old = world.handler

    def handler(req):
        if req.url.host == "api.github.com":
            return httpx.Response(200, json={"sha": "abc123", "commit": {"message": "Pôsteres\n\ndetalhes"}})
        if req.url.host == "codeload.github.com":
            return httpx.Response(200, content=payload)
        return old(req)

    hz.transport = httpx.MockTransport(handler)
    assert updater.check(hz)["disponivel"]
    res = updater.apply(hz, target=target, run_pip=False)
    assert res["atualizado"] and res["arquivos"] == 2
    assert (target / "horizonte" / "a.py").read_text() == "novo"
    assert (target / ".env").read_text() == "SEGREDO=meu"
    assert not (target / "data").exists()
    assert updater.check(hz)["disponivel"] is False
    assert updater.apply(hz, target=target)["atualizado"] is False
