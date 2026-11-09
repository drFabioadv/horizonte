import json
from urllib.parse import parse_qs

from conftest import connect_linkedin

from horizonte import editorial, linkedin, radar, xcentral
from horizonte.db import now_iso


def _produced(hz):
    radar.run_radar(hz)
    editorial.select_stories(hz)
    editorial.produce_pending(hz)
    return [r["id"] for r in hz.db.query("SELECT id FROM posts WHERE network='linkedin' ORDER BY id")]


def test_oauth_flow_and_token_encrypted(hz, world):
    url = linkedin.auth_url(hz)
    q = parse_qs(url.split("?", 1)[1])
    assert q["scope"] == ["openid profile w_member_social"] and q["redirect_uri"][0].endswith("/api/linkedin/callback")
    bad = linkedin.handle_callback(hz, "x", "estado-falso")
    assert not bad["ok"]
    connect_linkedin(hz)
    st = linkedin.status(hz)
    assert st["conectado"] and st["pode_publicar"] and st["nome"] == "Fabio Teste" and st["dias_restantes"] >= 59
    raw = hz.db.scalar("SELECT data FROM tokens WHERE provider='linkedin'")
    assert "TOKEN-SECRETO" not in raw
    logs = " ".join(r["message"] for r in hz.db.query("SELECT message FROM logs"))
    assert "TOKEN-SECRETO" not in logs and "CODIGO-DE-TESTE" not in logs


def test_publish_due_respects_auto_mode_and_pause(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    hz.db.execute("UPDATE posts SET scheduled_for=? WHERE network='linkedin'", (now_iso(),))
    assert linkedin.publish_due(hz)["aguardando"] == 3 and not world.posts_created
    hz.set_prefs({"linkedin_auto": True, "pausado": True})
    assert linkedin.publish_due(hz)["publicados"] == 0
    hz.set_prefs({"pausado": False})
    res = linkedin.publish_due(hz)
    assert res["publicados"] == 3
    rows = hz.db.query("SELECT status, external_url FROM posts WHERE network='linkedin'")
    assert all(r["status"] == "publicado" and r["external_url"].startswith("https://www.linkedin.com/feed/update/urn:li:share:") for r in rows)
    body = world.posts_created[0]
    assert body["author"] == "urn:li:person:abc123" and body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"
    assert "{hashtag|\\#|" in body["commentary"]  # hashtags no formato do LinkedIn
    assert "\\(" not in body["commentary"] or "(" not in body["commentary"].replace("\\(", "")
    assert all(v and len(v) == 6 for v in world.version_seen)
    # nada é publicado duas vezes
    assert linkedin.publish_due(hz)["publicados"] == 0 and len(world.posts_created) == 3
    assert linkedin.publish_post(hz, ids[0])["mensagem"] == "Já publicado."


def test_little_text_escaping():
    out = linkedin.to_little_text("Lei (nº 1) em vigor_ #Direito e @fulano")
    assert out == "Lei \\(nº 1\\) em vigor\\_ {hashtag|\\#|Direito} e \\@fulano"


def test_version_fallback_on_426(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    world.linkedin_mode = "426_once"
    res = linkedin.publish_post(hz, ids[0], force=True)
    assert res["ok"]
    assert world.version_seen[0] != world.version_seen[1]
    assert hz.db.get_pref("linkedin_api_version_ok") == world.version_seen[1]


def test_401_marks_reconnect_and_fails(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    world.linkedin_mode = "401"
    res = linkedin.publish_post(hz, ids[0], force=True)
    assert not res["ok"]
    assert hz.db.scalar("SELECT status FROM posts WHERE id=?", (ids[0],)) == "falhou"
    st = linkedin.status(hz)
    assert not st["conectado"] and "Reconecte" in st["mensagem"]


def test_429_reschedules(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    world.linkedin_mode = "429"
    linkedin.publish_post(hz, ids[0], force=True)
    row = hz.db.one("SELECT status, scheduled_for, error FROM posts WHERE id=?", (ids[0],))
    assert row["status"] == "agendado" and row["scheduled_for"] > now_iso() and "429" in row["error"]


def test_image_upload_when_authorized(hz, world):
    _produced(hz)
    connect_linkedin(hz)
    pid = hz.db.scalar("SELECT p.id FROM posts p JOIN stories s ON s.id=p.story_id WHERE p.network='linkedin' AND s.category='sociedade'")
    assert linkedin.publish_post(hz, pid, force=True)["ok"]
    assert world.posts_created[-1]["content"]["media"]["id"] == "urn:li:image:IMG1"
    assert any(c.url.host == "upload.linkedin.test" for c in world.calls)


def test_verification_change_suspends_before_publishing(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    story = hz.db.scalar("SELECT story_id FROM posts WHERE id=?", (ids[0],))
    cid = hz.db.scalar("SELECT cluster_id FROM stories WHERE id=?", (story,))
    hz.db.execute("UPDATE news SET published_at='2000-01-01T00:00:00+00:00' WHERE cluster_id=?", (cid,))
    res = linkedin.publish_post(hz, ids[0], force=True)
    assert not res["ok"] and "Suspenso" in res["mensagem"]
    assert hz.db.scalar("SELECT status FROM posts WHERE id=?", (ids[0],)) == "suspenso"
    assert not world.posts_created


def test_interrupted_publication_is_not_repeated(hz, world):
    ids = _produced(hz)
    connect_linkedin(hz)
    hz.db.execute("UPDATE posts SET status='publicando' WHERE id=?", (ids[0],))
    assert linkedin.recover_interrupted(hz) == 1
    assert hz.db.scalar("SELECT status FROM posts WHERE id=?", (ids[0],)) == "verificar"
    hz.set_prefs({"linkedin_auto": True})
    hz.db.execute("UPDATE posts SET scheduled_for=? WHERE network='linkedin'", (now_iso(),))
    linkedin.publish_due(hz)
    assert hz.db.scalar("SELECT status FROM posts WHERE id=?", (ids[0],)) == "verificar"
    assert linkedin.resolve_post(hz, ids[0], "marcar_publicado", "https://www.linkedin.com/feed/update/x/")["ok"]
    assert hz.db.scalar("SELECT status FROM posts WHERE id=?", (ids[0],)) == "publicado"


def test_test_publication_is_connections_only(hz, world):
    connect_linkedin(hz)
    res = linkedin.publish_test(hz)
    assert res["ok"] and world.posts_created[-1]["visibility"] == "CONNECTIONS"


def test_x_central_marks_manual_only(hz):
    _produced(hz)
    items = xcentral.list_items(hz)
    assert len(items) == 3 and all(i["situacao"] == "PRONTO PARA PUBLICAR" for i in items)
    assert xcentral.mark(hz, items[0]["id"], True, "https://x.com/u/status/1")["ok"]
    it = [i for i in xcentral.list_items(hz) if i["id"] == items[0]["id"]][0]
    assert it["situacao"] == "PUBLICADO MANUALMENTE" and it["external_url"].endswith("/1")
    xcentral.mark(hz, items[0]["id"], False)
    assert [i for i in xcentral.list_items(hz) if i["id"] == items[0]["id"]][0]["status"] == "pronto"
    # nenhuma chamada a qualquer API do X
    assert hz.db.scalar("SELECT COUNT(*) FROM posts WHERE network='x' AND external_id IS NOT NULL") == 0


def test_disconnect_turns_auto_off(hz, world):
    connect_linkedin(hz)
    hz.set_prefs({"linkedin_auto": True})
    linkedin.disconnect(hz)
    assert not linkedin.status(hz)["conectado"] and hz.prefs()["linkedin_auto"] is False
