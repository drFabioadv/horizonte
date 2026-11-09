from datetime import datetime, timedelta

from conftest import connect_linkedin
from fastapi.testclient import TestClient

from horizonte import editorial, radar, reports, scheduler
from horizonte.app import create_app
from horizonte.db import loads


def _full_day(hz):
    radar.run_radar(hz)
    editorial.select_stories(hz)
    editorial.produce_pending(hz)


def test_daily_report_and_exports(hz):
    _full_day(hz)
    rid = reports.generate(hz, "diario")
    data = loads(hz.db.scalar("SELECT data FROM reports WHERE id=?", (rid,)))
    assert data["titulo"] == "RELATÓRIO DIÁRIO HORIZONTE"
    assert data["resumo"]["noticias_monitoradas"] == 12 and data["resumo"]["pautas_selecionadas"] == 3
    assert len(data["linkedin"]) == 3 and len(data["x"]) == 3
    assert data["ocorrencias"]["restricoes_de_imagem"]
    assert any(d["status"] == "NÃO PUBLICAR" for d in data["ocorrencias"]["noticias_descartadas"])
    pdf = reports.to_pdf(hz, data)
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000
    csv = reports.to_csv(hz, data).decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("rede;titulo") and csv.count("LinkedIn;") == 3
    assert reports.generate(hz, "diario") == rid  # mesmo dia: atualiza, não duplica
    for kind in ("semanal", "mensal"):
        assert reports.generate(hz, kind)


def _at(hz, hh, mm, days=0):
    base = hz.local_now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    return base + timedelta(days=days)


def test_scheduler_runs_once_and_recovers(hz, world):
    fired = scheduler.tick(hz, _at(hz, 5, 0))
    assert "ciclo" not in fired and "radar" in fired
    fired = scheduler.tick(hz, _at(hz, 7, 0))
    assert "ciclo" in fired
    assert hz.db.scalar("SELECT COUNT(*) FROM stories") == 3
    fired = scheduler.tick(hz, _at(hz, 7, 1))
    assert "ciclo" not in fired and "radar" not in fired  # mesma faixa, nada duplicado
    # simula queda do PC no meio de uma rotina
    hz.db.execute("INSERT INTO runs(job, slot, status, started_at) VALUES ('radar','travado','em_execucao','2026-01-01')")
    assert scheduler.recover(hz)["rotinas"] == 1
    fired = scheduler.tick(hz, _at(hz, 22, 5))
    assert "relatorio" in fired
    assert scheduler.tick(hz, _at(hz, 22, 6)).count("relatorio") == 0


def test_scheduler_pause(hz):
    hz.set_prefs({"pausado": True})
    assert scheduler.tick(hz, _at(hz, 9, 0)) == []
    assert hz.db.scalar("SELECT COUNT(*) FROM runs") == 0


def test_scheduler_publishes_when_auto(hz, world):
    connect_linkedin(hz)
    hz.set_prefs({"linkedin_auto": True})
    scheduler.tick(hz, _at(hz, 7, 0))
    from horizonte.db import now_iso

    hz.db.execute("UPDATE posts SET scheduled_for=? WHERE network='linkedin'", (now_iso(),))
    fired = scheduler.tick(hz, _at(hz, 9, 0))
    assert "publicador" in fired and len(world.posts_created) == 3


def test_api_requires_login_and_works(hz):
    app = create_app(hz, start_scheduler=False)
    c = TestClient(app)
    assert c.get("/api/estado").status_code == 401
    assert c.get("/api/saude").status_code == 200
    assert c.post("/api/login", json={"chave": "errada"}).status_code == 401
    assert c.post("/api/login", json={"chave": "chave-teste"}).status_code == 200
    assert c.get("/api/estado").status_code == 200
    _full_day(hz)
    assert len(c.get("/api/radar").json()["itens"]) == 12
    assert len(c.get("/api/radar?categoria=direito").json()["itens"]) >= 2
    assert all(i["region"] == "PA" for i in c.get("/api/radar?regiao=PA").json()["itens"])
    pautas = c.get("/api/pautas").json()["itens"]
    assert len(pautas) == 3
    p = c.get(f"/api/pautas/{pautas[0]['id']}").json()
    assert p["fontes"] and p["posts"] and p["historico"]
    assert len(c.get("/api/x").json()["itens"]) == 3
    li = c.get("/api/linkedin").json()
    assert li["estado"]["configurado"] and len(li["posts"]) == 3
    assert c.post("/api/linkedin/modo", json={"automatico": True}).status_code == 400  # sem conta conectada
    assert c.put("/api/config", json={"horario_ciclo": "25h"}).status_code == 400
    r = c.put("/api/config", json={"linkedin_por_dia": 4, "linkedin_auto": True, "radar_intervalo_min": 5})
    prefs = r.json()["preferencias"]
    assert prefs["linkedin_por_dia"] == 4 and prefs["linkedin_auto"] is False and prefs["radar_intervalo_min"] == 15
    rid = c.post("/api/relatorios/gerar", json={"tipo": "diario"}).json()["id"]
    assert c.get(f"/api/relatorios/{rid}/pdf").content[:4] == b"%PDF"
    assert c.get(f"/api/relatorios/{rid}/csv").status_code == 200
    assert len(c.get("/api/fontes").json()["itens"]) == 5
    assert c.get("/").status_code == 200 and "HORIZONTE" in c.get("/").text
    assert c.post("/api/linkedin/teste", json={}).status_code == 400  # exige confirmação explícita
    up = c.post(f"/api/posts/{li['posts'][0]['id']}/imagem", files={"arquivo": ("foto.png", b"\x89PNG....", "image/png")})
    assert up.status_code == 200 and up.json()["imagem"]["autorizada"]
