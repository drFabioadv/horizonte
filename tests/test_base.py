from horizonte.classify import classify
from horizonte.db import Database
from horizonte.security import Vault, redact, token_ok
from horizonte.textutil import canonical_url, numbers, x_length


def test_redact_removes_tokens():
    msg = "Authorization: Bearer AQX1234567890abcdef access_token=abcdefghijk client_secret=xyz12345 ?code=ABCDEFGH123"
    out = redact(msg)
    assert "AQX1234567890" not in out and "abcdefghijk" not in out and "xyz12345" not in out and "ABCDEFGH123" not in out
    assert out.count("***") == 4


def test_vault_roundtrip_and_tamper():
    from cryptography.fernet import Fernet

    v = Vault(Fernet.generate_key().decode())
    blob = v.encrypt({"access_token": "segredo"})
    assert "segredo" not in blob
    assert v.decrypt(blob) == {"access_token": "segredo"}
    assert v.decrypt(blob[:-4] + "AAAA") is None


def test_token_ok():
    assert token_ok("abc", "abc") and not token_ok("abd", "abc") and not token_ok(None, "abc")


def test_database_migrate_is_idempotent(tmp_path):
    db = Database(tmp_path / "x.db")
    db.set_pref("a", {"b": 1})
    db.migrate()
    assert db.get_pref("a") == {"b": 1}
    assert db.prefs({"a": None, "z": 5}) == {"a": {"b": 1}, "z": 5}


def test_canonical_url_strips_tracking():
    assert canonical_url("https://www.site.com/a/b/?utm_source=rss&id=3#x") == canonical_url("https://site.com/a/b?id=3")


def test_numbers_and_x_length():
    assert numbers("Foram 62 votos a 8; R$ 1.200,50 e 32% de abstenção em 2026") == {"62", "1200,50", "32", "2026"}
    assert x_length("abc https://muito.longo/" + "x" * 80) == len("abc ") + 23


def test_classify_categories_region_flags():
    src = {"tier": "imprensa", "category_hint": None, "region": "BR"}
    a = classify("STF julga constitucionalidade de lei estadual", "", src)
    assert a["category"] == "direito"
    b = classify("Senado aprova projeto de lei sobre transparência", "", src)
    assert b["category"] == "politica" and "proposicao" in b["flags"]
    c = classify("PF prende suspeito de fraude em Belém", "", src)
    assert c["region"] == "PA" and "acusacao" in c["flags"]
    d = classify("Enem tem abstenção de 32% no primeiro dia", "", src)
    assert d["category"] == "sociedade"
    e = classify("Previsão do tempo", "", src)
    assert "titulo_curto" in e["flags"] and e["relevance"] <= 10
    # "sempre " não deve casar com o termo "re " (réu)
    f = classify("Governo sempre defende a reforma", "", src)
    assert "acusacao" not in f["flags"]
