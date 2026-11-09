from horizonte import editorial, radar
from horizonte.db import loads
from horizonte.textutil import x_length


def _ready(hz):
    radar.run_radar(hz)
    return editorial.select_stories(hz)


def test_selection_balances_areas_and_skips_unverified(hz):
    sel = _ready(hz)
    assert len(sel["selecionadas"]) == 3
    stories = [dict(r) for r in hz.db.query("SELECT s.*, c.verification FROM stories s JOIN clusters c ON c.id=s.cluster_id")]
    assert {s["category"] for s in stories} == {"direito", "politica", "sociedade"}
    assert all(s["verification"] == "VERIFICADA" for s in stories)
    again = editorial.select_stories(hz)
    assert again["selecionadas"] == []  # meta já atingida, nada duplicado


def test_selection_reports_shortage_honestly(hz):
    radar.run_radar(hz)
    hz.set_prefs({"linkedin_por_dia": 6, "x_por_dia": 6})
    sel = editorial.select_stories(hz)
    assert len(sel["selecionadas"]) == 3
    assert sel["motivo"] and "não completa a meta" in sel["motivo"]


def test_production_creates_linkedin_and_x(hz, world):
    _ready(hz)
    out = editorial.produce_pending(hz)
    assert out["produzidas"] == 3 and out["falhas"] == 0
    li = [dict(r) for r in hz.db.query("SELECT * FROM posts WHERE network='linkedin'")]
    xs = [dict(r) for r in hz.db.query("SELECT * FROM posts WHERE network='x'")]
    assert len(li) == 3 and len(xs) == 3
    for p in li:
        assert p["status"] == "agendado" and p["scheduled_for"]
        assert "Fontes consultadas:" in p["body"] and "HORIZONTE — Direito. Política. Sociedade." in p["body"]
        assert len(loads(p["hashtags"])) <= 5
    for p in xs:
        assert p["status"] == "pronto"
        assert x_length(p["body"]) <= 280
        assert p["body"].count("#") <= 3
    assert len({p["scheduled_for"] for p in li}) == 3  # horários diferentes
    st = hz.db.query("SELECT status, analysis FROM stories")
    assert all(r["status"] == "pronta" and loads(r["analysis"])["analise_critica"] for r in st)


def test_authorized_image_only(hz):
    _ready(hz)
    editorial.produce_pending(hz)
    enem = hz.db.one("SELECT p.image FROM posts p JOIN stories s ON s.id=p.story_id WHERE p.network='x' AND s.category='sociedade'")
    img = loads(enem["image"])
    assert img["autorizada"] and img["credito"].startswith("Foto: Agência Brasil")
    pec = hz.db.one("SELECT p.image FROM posts p JOIN stories s ON s.id=p.story_id WHERE p.network='x' AND s.category='politica'")
    img = loads(pec["image"])
    assert img["autorizada"] is False and img["url"] is None and "não tem autorização" in img["observacao"]


def test_guard_retries_then_passes(hz, world):
    world.llm_mode = "bad_once"
    _ready(hz)
    out = editorial.produce_pending(hz)
    assert out["produzidas"] == 3
    assert world.llm_calls == 12  # análise e adaptação: 2 tentativas cada, por pauta
    assert not any("73%" in r["body"] for r in hz.db.query("SELECT body FROM posts"))


def test_guard_suspends_when_invention_persists(hz, world):
    world.llm_mode = "always_bad"
    _ready(hz)
    out = editorial.produce_pending(hz)
    assert out["produzidas"] == 0
    rows = hz.db.query("SELECT status, reason FROM stories")
    assert all(r["status"] == "suspensa" and "73" in r["reason"] for r in rows)
    assert hz.db.scalar("SELECT COUNT(*) FROM posts") == 0


def test_without_local_ai_nothing_is_invented(hz, world):
    world.ollama_up = False
    _ready(hz)
    out = editorial.produce_pending(hz)
    assert out["sem_ia"] and out["produzidas"] == 0
    assert hz.db.scalar("SELECT COUNT(*) FROM posts") == 0
    assert hz.db.scalar("SELECT COUNT(*) FROM stories WHERE status='aguardando_ia'") == 1
    assert hz.db.scalar("SELECT MAX(attempts) FROM stories") == 0
    world.ollama_up = True
    out = editorial.produce_pending(hz)
    assert out["produzidas"] == 3


def test_check_text_rules():
    pack = "O Senado aprovou o projeto de lei por 62 votos. Segundo a PF, o suspeito é investigado."
    assert editorial.check_text("Aprovado por 62 votos.", pack, [], 2026) == []
    assert any("Números" in p for p in editorial.check_text("Aprovado por 63 votos.", pack, [], 2026))
    assert any("proposição" in p for p in editorial.check_text("A nova lei entra em vigor.", pack, ["proposicao"], 2026))
    assert any("culpa" in p for p in editorial.check_text("O criminoso foi preso.", pack, ["acusacao"], 2026))
    assert any("Citação" in p for p in editorial.check_text('Ele disse: "vamos mudar tudo neste país agora".', pack, [], 2026))
    assert any("campanha" in p for p in editorial.check_text("Vote em quem defende isso.", pack, [], 2026))
