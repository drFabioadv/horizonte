from horizonte import radar
from horizonte.db import loads


def _cluster_of(hz, title_part):
    row = hz.db.one(
        "SELECT c.* FROM clusters c JOIN news n ON n.cluster_id=c.id WHERE n.title LIKE ? LIMIT 1", (f"%{title_part}%",))
    return dict(row)


def test_radar_stores_and_deduplicates(hz):
    first = radar.run_radar(hz)
    assert first["erros"] == 0
    n = hz.db.scalar("SELECT COUNT(*) FROM news")
    assert first["novas"] == n == 12
    second = radar.run_radar(hz)
    assert second["novas"] == 0
    assert hz.db.scalar("SELECT COUNT(*) FROM news") == n
    # link com utm_source foi normalizado
    assert hz.db.scalar("SELECT url_canon FROM news WHERE title LIKE 'Senado aprova PEC%' AND url LIKE '%senado.test%'") == \
        "https://senado.test/n/pec-seguranca"


def test_same_fact_is_grouped_across_sources(hz):
    radar.run_radar(hz)
    c = _cluster_of(hz, "PEC da Segurança")
    assert c["n_orgs"] == 3 and c["has_primary"] == 1
    assert c["verification"] == "VERIFICADA"
    enem = _cluster_of(hz, "Enem 2026")
    assert enem["n_orgs"] == 2 and enem["verification"] == "VERIFICADA" and enem["category"] == "sociedade"
    stf = _cluster_of(hz, "proteção de dados de servidores")
    assert stf["n_orgs"] == 2 and stf["category"] == "direito"


def test_verification_statuses(hz):
    radar.run_radar(hz)
    pf = _cluster_of(hz, "PF prende")
    assert pf["verification"] == "EM CONFERÊNCIA"
    assert any("acusação" in n for n in loads(pf["verification_notes"]))
    assert any("não significa" in n or "Aguardando" in n for n in loads(pf["verification_notes"]))
    old = _cluster_of(hz, "reforma administrativa em 2019")
    assert old["verification"] == "NÃO PUBLICAR"
    verbas = _cluster_of(hz, "saúde indígena")
    assert verbas["verification"] == "CONTROVERSA"
    tempo = _cluster_of(hz, "Previsão do tempo")
    assert tempo["verification"] == "NÃO PUBLICAR"


def test_source_errors_are_recorded(hz, world):
    hz.db.execute("UPDATE sources SET feed_url='https://quebrado.test/rss' WHERE org='conjur'")
    res = radar.run_radar(hz)
    assert res["erros"] == 1
    row = hz.db.one("SELECT last_status, last_error FROM sources WHERE org='conjur'")
    assert row["last_status"] == "erro" and "404" in row["last_error"]
