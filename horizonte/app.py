"""Servidor web local do HORIZONTE (painel + API)."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, editorial, images, linkedin, llm, nuvem, pipeline, radar, reports, xcentral
from .config import DEFAULT_PREFS
from .core import Horizonte
from .db import dumps, loads, now_iso, row_dict, utcnow
from .scheduler import Scheduler
from .security import token_ok

WEB = Path(__file__).parent / "web"
COOKIE = "hz_sessao"
OPEN_PATHS = {"/api/saude", "/api/login", "/api/linkedin/callback"}
LOGIN_CODE_TTL = 120  # segundos


def create_app(hz: Horizonte | None = None, start_scheduler: bool = True) -> FastAPI:
    hz = hz or Horizonte()
    jobs: dict[str, dict] = {}
    sched = Scheduler(hz) if start_scheduler else None
    session_value = hmac.new(hz.settings.secret_key.encode(), hz.settings.admin_token.encode(), hashlib.sha256).hexdigest()

    @asynccontextmanager
    async def lifespan(_app):
        if sched:
            sched.start()
        yield
        if sched:
            sched.stop()

    app = FastAPI(title="HORIZONTE", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.hz = hz
    app.state.scheduler = sched
    login_codes: dict[str, float] = {}

    def issue_login() -> str:
        """Código de uso único para o ícone da bandeja abrir o painel já logado."""
        import time as _t

        code = secrets.token_urlsafe(24)
        now = _t.time()
        for k, exp in list(login_codes.items()):
            if exp < now:
                login_codes.pop(k, None)
        login_codes[code] = now + LOGIN_CODE_TTL
        return code

    app.state.issue_login = issue_login

    # ------------------------------------------------------------ segurança
    @app.middleware("http")
    async def auth(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in OPEN_PATHS:
            sid = request.cookies.get(COOKIE)
            header = request.headers.get("x-horizonte-token")
            if not (token_ok(sid, session_value) or token_ok(header, hz.settings.admin_token)):
                return JSONResponse({"detail": "Acesso restrito. Entre com a chave do painel."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.post("/api/login")
    def login(payload: dict = Body(...)):
        if not token_ok(str(payload.get("chave", "")), hz.settings.admin_token):
            raise HTTPException(401, "Chave incorreta.")
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, session_value, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return resp

    @app.get("/entrar")
    def entrar(c: str = ""):
        import time as _t

        exp = login_codes.pop(c, None)
        resp = RedirectResponse("/", status_code=303)
        if exp and exp >= _t.time():
            resp.set_cookie(COOKIE, session_value, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return resp

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/api/saude")
    def saude():
        return {"ok": True, "versao": __version__}

    # ------------------------------------------------------------ tarefas em segundo plano
    def background(name: str, fn, *args):
        if jobs.get(name, {}).get("rodando"):
            return {"ok": False, "mensagem": "Já está em andamento."}
        jobs[name] = {"rodando": True, "inicio": now_iso(), "resultado": None}

        def run():
            try:
                jobs[name]["resultado"] = fn(*args)
            except Exception as e:
                hz.log("error", "painel", f"{name}: {e}")
                jobs[name]["resultado"] = {"erro": str(e)}
            finally:
                jobs[name]["rodando"] = False
                jobs[name]["fim"] = now_iso()

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "mensagem": "Iniciado."}

    @app.get("/api/tarefas")
    def tarefas():
        return jobs

    # ------------------------------------------------------------ dashboard
    @app.get("/api/estado")
    def estado():
        day = hz.today()
        a, b = hz.day_bounds_utc(day)
        prefs = hz.prefs()
        q1 = hz.db.scalar
        posts_today = [dict(r) for r in hz.db.query(
            "SELECT p.network, p.status FROM posts p JOIN stories s ON s.id=p.story_id WHERE s.day=?", (day.isoformat(),))]
        recent = [dict(r) for r in hz.db.query(
            "SELECT ts, level, module, message FROM logs ORDER BY id DESC LIMIT 12")]
        last_cycle = row_dict(hz.db.one("SELECT * FROM runs WHERE job='ciclo' ORDER BY started_at DESC LIMIT 1"))
        last_radar = row_dict(hz.db.one("SELECT * FROM runs WHERE job='radar' ORDER BY started_at DESC LIMIT 1"))
        upcoming = [row_dict(r, ("sources",)) for r in hz.db.query(
            "SELECT id, title, category, status, scheduled_for FROM posts WHERE network='linkedin' AND status='agendado' "
            "ORDER BY scheduled_for LIMIT 5")]
        return {
            "agora": hz.local_now().isoformat(timespec="minutes"),
            "dia": day.isoformat(),
            "pausado": prefs["pausado"],
            "metas": {"linkedin": prefs["linkedin_por_dia"], "x": prefs["x_por_dia"]},
            "hoje": {
                "noticias": q1("SELECT COUNT(*) FROM news WHERE fetched_at>=? AND fetched_at<?", (a, b)) or 0,
                "verificadas": q1("SELECT COUNT(*) FROM clusters WHERE last_seen>=? AND verification='VERIFICADA'", (a,)) or 0,
                "pautas": q1("SELECT COUNT(*) FROM stories WHERE day=?", (day.isoformat(),)) or 0,
                "prontas": q1("SELECT COUNT(*) FROM stories WHERE day=? AND status IN ('pronta','publicada')", (day.isoformat(),)) or 0,
                "linkedin_publicados": sum(1 for p in posts_today if p["network"] == "linkedin" and p["status"] == "publicado"),
                "linkedin_agendados": sum(1 for p in posts_today if p["network"] == "linkedin" and p["status"] == "agendado"),
                "x_pendentes": sum(1 for p in posts_today if p["network"] == "x" and p["status"] == "pronto"),
                "x_publicados": sum(1 for p in posts_today if p["network"] == "x" and p["status"] == "publicado_manual"),
            },
            "conexoes": {"linkedin": linkedin.status(hz), "ia": llm.status(hz), "x": {"modo": "manual",
                         "mensagem": "Publicação manual pela Central do X (sem API paga)."}},
            "ultimo_ciclo": last_cycle,
            "ultimo_radar": last_radar,
            "agendador": {"ativo": bool(sched), "ultimo_tique": sched.last_tick if sched else None},
            "proximas_linkedin": upcoming,
            "atividade": recent,
            "fontes": {"ligadas": q1("SELECT COUNT(*) FROM sources WHERE enabled=1") or 0,
                       "com_erro": q1("SELECT COUNT(*) FROM sources WHERE enabled=1 AND last_status='erro'") or 0},
        }

    @app.post("/api/operacao")
    def operacao(payload: dict = Body(...)):
        paused = bool(payload.get("pausado"))
        hz.set_prefs({"pausado": paused})
        hz.log("info", "painel", "Operação pausada." if paused else "Operação retomada.")
        return {"ok": True, "pausado": paused}

    @app.post("/api/ciclo/executar")
    def ciclo_agora():
        return background("ciclo", pipeline.daily_cycle, hz)

    # ------------------------------------------------------------ radar
    @app.get("/api/radar")
    def radar_list(categoria: str = "", regiao: str = "", fonte: int = 0, status: str = "", desde: str = "",
                   q: str = "", ordem: str = "relevancia", limite: int = 150):
        sql = ("SELECT n.id, n.title, n.summary, n.url, n.published_at, n.fetched_at, n.category, n.region, n.relevance, "
               "n.flags, n.is_update, s.name AS fonte, s.id AS fonte_id, s.tier, c.id AS grupo, c.verification, c.n_orgs, "
               "c.verification_notes FROM news n JOIN sources s ON s.id=n.source_id LEFT JOIN clusters c ON c.id=n.cluster_id WHERE 1=1")
        params: list = []
        if categoria:
            sql += " AND n.category=?"; params.append(categoria)
        if regiao:
            sql += " AND n.region=?"; params.append(regiao)
        if fonte:
            sql += " AND s.id=?"; params.append(fonte)
        if status:
            sql += " AND c.verification=?"; params.append(status)
        if desde:
            sql += " AND COALESCE(n.published_at, n.fetched_at)>=?"; params.append(desde)
        else:
            sql += " AND n.fetched_at>=?"; params.append((utcnow() - timedelta(hours=72)).isoformat(timespec="seconds"))
        if q:
            sql += " AND (n.title LIKE ? OR n.summary LIKE ?)"; params += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY " + ("COALESCE(n.published_at, n.fetched_at) DESC" if ordem == "data" else "n.relevance DESC, n.published_at DESC")
        sql += " LIMIT ?"; params.append(min(500, limite))
        rows = [row_dict(r, ("flags", "verification_notes")) for r in hz.db.query(sql, params)]
        return {"itens": rows, "fontes": [dict(r) for r in hz.db.query("SELECT id, name FROM sources WHERE enabled=1 ORDER BY name")]}

    @app.post("/api/radar/atualizar")
    def radar_now():
        return background("radar", radar.run_radar, hz)

    # ------------------------------------------------------------ central editorial
    def _story_payload(sid: int) -> dict | None:
        st = row_dict(hz.db.one("SELECT * FROM stories WHERE id=?", (sid,)), ("analysis",))
        if not st:
            return None
        st["grupo"] = row_dict(hz.db.one("SELECT * FROM clusters WHERE id=?", (st["cluster_id"],)), ("verification_notes", "flags"))
        st["fontes"] = [dict(r) for r in hz.db.query(
            "SELECT n.id, n.title, n.url, n.published_at, n.summary, s.name AS fonte, s.tier FROM news n JOIN sources s ON s.id=n.source_id "
            "WHERE n.cluster_id=? ORDER BY n.published_at DESC", (st["cluster_id"],))]
        st["posts"] = [row_dict(r, ("hashtags", "sources", "thread", "image")) for r in hz.db.query(
            "SELECT * FROM posts WHERE story_id=? ORDER BY network", (sid,))]
        st["historico"] = [dict(r) for r in hz.db.query(
            "SELECT ts, event, detail FROM story_events WHERE story_id=? ORDER BY id", (sid,))]
        st["explicacao"] = _explain(st)
        return st

    def _explain(st: dict) -> dict:
        """Traduz os avisos em vermelho: por que está assim e o que dá para fazer."""
        from .verify import EXPLICACAO, bloqueio_publicacao, verify_cluster

        check = verify_cluster(hz, st["cluster_id"]) or {}
        st["grupo"]["verification"] = check.get("status", st["grupo"].get("verification"))
        st["grupo"]["verification_notes"] = check.get("notes", st["grupo"].get("verification_notes"))
        motivo = check.get("motivo")
        bloqueia = bool(bloqueio_publicacao(check))
        itens = []
        if check.get("status") and check["status"] != "VERIFICADA":
            itens.append({"tipo": "verificacao", "titulo": f"Selo {check['status']}",
                          "texto": EXPLICACAO.get(motivo or "", " ".join(check.get("notes", [])[-1:])),
                          "bloqueia": bloqueia})
        if st["status"] == "suspensa" and st.get("reason"):
            itens.append({"tipo": "pauta", "titulo": "Por que a pauta foi suspensa", "texto": st["reason"],
                          "bloqueia": True})
        for p in st["posts"]:
            if p["network"] == "linkedin" and p["status"] == "suspenso" and p.get("error") \
                    and p["error"].split(": ", 1)[-1] not in (st.get("reason") or ""):
                itens.append({"tipo": "post", "post": p["id"], "titulo": "Por que o post do LinkedIn está segurado",
                              "texto": p["error"], "bloqueia": True})
        return {"itens": itens, "motivo": motivo, "bloqueia_publicacao": bloqueia}

    @app.get("/api/pautas")
    def pautas(dia: str = "", status: str = "", limite: int = 80):
        sql = ("SELECT s.id, s.day, s.category, s.status, s.reason, s.updated_at, c.title, c.verification, c.n_orgs, c.score "
               "FROM stories s JOIN clusters c ON c.id=s.cluster_id WHERE 1=1")
        params: list = []
        if dia:
            sql += " AND s.day=?"; params.append(dia)
        if status:
            sql += " AND s.status=?"; params.append(status)
        sql += " ORDER BY s.day DESC, s.id DESC LIMIT ?"; params.append(limite)
        return {"itens": [dict(r) for r in hz.db.query(sql, params)]}

    @app.get("/api/pautas/{sid}")
    def pauta(sid: int):
        st = _story_payload(sid)
        if not st:
            raise HTTPException(404, "Pauta não encontrada.")
        return st

    @app.post("/api/pautas/{sid}/suspender")
    def suspender(sid: int, payload: dict = Body(default={})):
        nuvem.soon()
        reason = payload.get("motivo") or "Suspensa manualmente pelo usuário."
        hz.db.execute("UPDATE stories SET status='suspensa', reason=?, updated_at=? WHERE id=?", (reason, now_iso(), sid))
        hz.db.execute("UPDATE posts SET status='suspenso', error=?, updated_at=? WHERE story_id=? AND status IN ('agendado','pronto')",
                      (reason, now_iso(), sid))
        hz.db.execute("INSERT INTO story_events(story_id, ts, event, detail) VALUES (?,?,?,?)", (sid, now_iso(), "suspensa", reason))
        return {"ok": True}

    @app.post("/api/pautas/{sid}/produzir")
    def produzir(sid: int):
        hz.db.execute("UPDATE stories SET status='selecionada', attempts=0 WHERE id=? AND status IN ('suspensa','aguardando_ia')", (sid,))
        return background(f"produzir-{sid}", editorial.produce_story, hz, sid)

    # ------------------------------------------------------------ LinkedIn
    @app.get("/api/linkedin")
    def li_panel():
        posts = [row_dict(r, ("hashtags", "sources", "image")) for r in hz.db.query(
            "SELECT * FROM posts WHERE network='linkedin' ORDER BY COALESCE(scheduled_for, created_at) DESC LIMIT 80")]
        return {"estado": linkedin.status(hz), "posts": posts, "nuvem": nuvem.status(hz)}

    @app.get("/api/linkedin/conectar")
    def li_connect():
        if not linkedin.configured(hz):
            return HTMLResponse(_simple_page("LinkedIn não configurado",
                                             "Preencha LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET no arquivo .env e reinicie o HORIZONTE."))
        return RedirectResponse(linkedin.auth_url(hz))

    @app.get("/api/linkedin/callback")
    def li_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                    error_description: str | None = None):
        res = linkedin.handle_callback(hz, code, state, error_description or error)
        title = "LinkedIn conectado" if res["ok"] else "Não foi possível conectar"
        return HTMLResponse(_simple_page(title, res["mensagem"], back=True))

    @app.post("/api/linkedin/desconectar")
    def li_disconnect():
        return linkedin.disconnect(hz)

    @app.post("/api/linkedin/modo")
    def li_mode(payload: dict = Body(...)):
        auto = bool(payload.get("automatico"))
        if auto and not linkedin.status(hz)["pode_publicar"]:
            raise HTTPException(400, "Conecte a conta com a permissão de publicar antes de ligar o modo automático.")
        hz.set_prefs({"linkedin_auto": auto})
        hz.log("info", "linkedin", "Modo automático ligado." if auto else "Modo automático desligado.")
        return {"ok": True, "automatico": auto}

    @app.post("/api/linkedin/teste")
    def li_test(payload: dict = Body(...)):
        if not payload.get("confirmo"):
            raise HTTPException(400, "Confirme que deseja publicar o teste.")
        return linkedin.publish_test(hz)

    @app.post("/api/linkedin/posts/{pid}/publicar")
    def li_publish_now(pid: int):
        nuvem.soon()
        hz.db.execute("UPDATE posts SET scheduled_for=? WHERE id=? AND status='agendado'", (now_iso(), pid))
        return linkedin.publish_post(hz, pid, force=True)

    @app.post("/api/linkedin/posts/{pid}/resolver")
    def li_resolve(pid: int, payload: dict = Body(...)):
        nuvem.soon()
        return linkedin.resolve_post(hz, pid, str(payload.get("acao")), payload.get("url"))

    @app.put("/api/posts/{pid}/texto")
    def edit_text(pid: int, payload: dict = Body(...)):
        nuvem.soon()
        text = str(payload.get("texto", "")).strip()
        if not text:
            raise HTTPException(400, "O texto não pode ficar vazio.")
        row = hz.db.one("SELECT network, status FROM posts WHERE id=?", (pid,))
        if not row or row["status"] in ("publicado", "publicando"):
            raise HTTPException(400, "Este post não pode mais ser editado.")
        hz.db.execute("UPDATE posts SET body=?, content_hash=?, updated_at=? WHERE id=?",
                      (text, editorial.content_hash(row["network"], text), now_iso(), pid))
        return {"ok": True}

    @app.post("/api/posts/{pid}/imagem")
    async def upload(pid: int, arquivo: UploadFile = File(...)):
        nuvem.soon()
        if arquivo.content_type not in ("image/jpeg", "image/png", "image/gif"):
            raise HTTPException(400, "Envie JPG, PNG ou GIF.")
        data = await arquivo.read()
        if len(data) > 8_000_000:
            raise HTTPException(400, "Imagem acima de 8 MB.")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}[arquivo.content_type]
        path = hz.settings.data_dir / "uploads" / f"post{pid}-{secrets.token_hex(4)}{ext}"
        path.write_bytes(data)
        img = images.user_image(path, re.sub(r"[^\w.\- ]", "", arquivo.filename or "imagem"))
        hz.db.execute("UPDATE posts SET image=?, updated_at=? WHERE id=?", (dumps(img), now_iso(), pid))
        return {"ok": True, "imagem": img}

    @app.post("/api/posts/{pid}/revalidar")
    def post_revalidar(pid: int):
        nuvem.soon()
        return editorial.revalidate_post(hz, pid)

    @app.post("/api/posts/{pid}/liberar")
    def post_liberar(pid: int, payload: dict = Body(default={})):
        if not payload.get("confirmo"):
            raise HTTPException(400, "Confirme que quer publicar mesmo com o aviso.")
        nuvem.soon()
        return editorial.override_post(hz, pid)

    @app.post("/api/pautas/{sid}/poster")
    def pauta_poster(sid: int, payload: dict = Body(default={})):
        nuvem.soon()
        img = editorial.attach_poster(hz, sid, frase=str(payload.get("frase") or "")[:300] or None)
        if not img:
            raise HTTPException(400, "Esta pauta não tem post do LinkedIn aguardando publicação.")
        return {"ok": True, "imagem": img}

    @app.get("/api/nuvem")
    def nuvem_status():
        return nuvem.status(hz)

    @app.post("/api/nuvem/sincronizar")
    def nuvem_sync():
        return nuvem.sync(hz, force_push=True)

    @app.post("/api/poster/livre")
    def poster_livre(payload: dict = Body(...)):
        from . import poster

        frase = str(payload.get("frase") or "").strip()[:400]
        if not frase:
            raise HTTPException(400, "Escreva a frase do pôster.")
        autor = poster.autor_de(hz.prefs())
        outro = str(payload.get("autor") or "").strip()[:60]
        if outro and outro != autor["nome"]:
            autor = {**autor, "nome": outro, "titulo": ""}
        path = poster.save(hz, poster.render_free(frase, autor, payload.get("categoria")), "livre")
        return {"ok": True, "url": f"/uploads/{path.name}"}

    @app.get("/uploads/{name}")
    def uploaded(name: str):
        p = (hz.settings.data_dir / "uploads" / Path(name).name)
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p)

    # ------------------------------------------------------------ X
    @app.get("/api/x")
    def x_list(dia: str = "", status: str = ""):
        return {"itens": xcentral.list_items(hz, dia or None, status or None)}

    @app.post("/api/x/{pid}/publicado")
    def x_mark(pid: int, payload: dict = Body(...)):
        return xcentral.mark(hz, pid, bool(payload.get("publicado")), payload.get("url"))

    @app.post("/api/x/{pid}/descartar")
    def x_discard(pid: int):
        return xcentral.discard(hz, pid)

    # ------------------------------------------------------------ relatórios
    @app.get("/api/relatorios")
    def rel_list(tipo: str = ""):
        sql = "SELECT id, kind, period_start, period_end, created_at FROM reports"
        params: list = []
        if tipo:
            sql += " WHERE kind=?"; params.append(tipo)
        sql += " ORDER BY period_start DESC, kind LIMIT 120"
        return {"itens": [dict(r) for r in hz.db.query(sql, params)]}

    @app.post("/api/relatorios/gerar")
    def rel_generate(payload: dict = Body(default={})):
        kind = payload.get("tipo", "diario")
        if kind not in ("diario", "semanal", "mensal"):
            raise HTTPException(400, "Tipo inválido.")
        day = date.fromisoformat(payload["data"]) if payload.get("data") else hz.today()
        return {"ok": True, "id": reports.generate(hz, kind, day)}

    def _report(rid: int) -> dict:
        row = hz.db.one("SELECT data FROM reports WHERE id=?", (rid,))
        if not row:
            raise HTTPException(404, "Relatório não encontrado.")
        return loads(row["data"])

    @app.get("/api/relatorios/{rid}")
    def rel_get(rid: int):
        return _report(rid)

    @app.get("/api/relatorios/{rid}/pdf")
    def rel_pdf(rid: int):
        data = _report(rid)
        name = f"horizonte-{data['tipo']}-{data['periodo']['inicio']}.pdf"
        return Response(reports.to_pdf(hz, data), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/relatorios/{rid}/csv")
    def rel_csv(rid: int):
        data = _report(rid)
        name = f"horizonte-{data['tipo']}-{data['periodo']['inicio']}.csv"
        return Response(reports.to_csv(hz, data), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------ configurações e fontes
    @app.get("/api/config")
    def config_get():
        prefs = hz.prefs()
        return {"preferencias": prefs, "padroes": DEFAULT_PREFS, "ia": llm.status(hz),
                "ambiente": {"fuso": hz.settings.timezone, "pasta_dados": str(hz.settings.data_dir),
                             "linkedin_configurado": linkedin.configured(hz), "endereco": hz.settings.public_url}}

    @app.put("/api/config")
    def config_put(payload: dict = Body(...)):
        clean = {}
        for k, v in payload.items():
            if k not in DEFAULT_PREFS or k in ("linkedin_auto", "pausado"):
                continue
            default = DEFAULT_PREFS[k]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = max(0, int(v))
            elif isinstance(default, list):
                v = [str(x).strip() for x in v if re.fullmatch(r"\d{2}:\d{2}", str(x).strip())]
            elif isinstance(default, dict):
                v = {kk: max(0, int(v.get(kk, default[kk]))) for kk in default}
            elif k in ("horario_ciclo", "horario_relatorio") and not re.fullmatch(r"\d{2}:\d{2}", str(v)):
                raise HTTPException(400, f"Horário inválido em {k}. Use HH:MM.")
            clean[k] = v
        if "radar_intervalo_min" in clean:
            clean["radar_intervalo_min"] = max(15, clean["radar_intervalo_min"])
        return {"ok": True, "preferencias": hz.set_prefs(clean)}

    @app.get("/api/fontes")
    def fontes():
        return {"itens": [dict(r) for r in hz.db.query("SELECT * FROM sources ORDER BY group_name, name")]}

    @app.post("/api/fontes")
    def fonte_nova(payload: dict = Body(...)):
        name = str(payload.get("name", "")).strip()
        homepage = str(payload.get("homepage", "")).strip()
        if not name or not homepage.startswith("http"):
            raise HTTPException(400, "Informe nome e endereço (http...).")
        cur = hz.db.execute(
            "INSERT INTO sources(name, org, tier, group_name, homepage, feed_url, category_hint, region, image_policy, enabled) "
            "VALUES (?,?,?,?,?,?,?,?,?,1)",
            (name, payload.get("org") or re.sub(r"\W+", "-", name.lower()), payload.get("tier", "imprensa"),
             payload.get("group_name", "jornalistica"), homepage, payload.get("feed_url") or None,
             payload.get("category_hint") or None, payload.get("region", "BR"), payload.get("image_policy", "nao_liberada")),
        )
        sid = cur.lastrowid
        if not payload.get("feed_url"):
            radar.test_source(hz, sid)
        return {"ok": True, "id": sid}

    @app.put("/api/fontes/{sid}")
    def fonte_editar(sid: int, payload: dict = Body(...)):
        allowed = {"name", "org", "tier", "group_name", "homepage", "feed_url", "category_hint", "region", "image_policy",
                   "enabled", "note"}
        sets = {k: v for k, v in payload.items() if k in allowed}
        if not sets:
            return {"ok": True}
        hz.db.execute(f"UPDATE sources SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), sid))
        return {"ok": True}

    @app.delete("/api/fontes/{sid}")
    def fonte_remover(sid: int):
        if hz.db.scalar("SELECT 1 FROM news WHERE source_id=? LIMIT 1", (sid,)):
            hz.db.execute("UPDATE sources SET enabled=0 WHERE id=?", (sid,))
            return {"ok": True, "mensagem": "A fonte tem histórico; foi desligada em vez de apagada."}
        hz.db.execute("DELETE FROM sources WHERE id=?", (sid,))
        return {"ok": True}

    @app.post("/api/fontes/{sid}/testar")
    def fonte_testar(sid: int):
        return radar.test_source(hz, sid)

    @app.get("/api/ia")
    def ia_status():
        return llm.status(hz)

    @app.get("/api/logs")
    def logs(nivel: str = "", limite: int = 200):
        sql = "SELECT * FROM logs"
        params: list = []
        if nivel:
            sql += " WHERE level=?"; params.append(nivel.upper())
        sql += " ORDER BY id DESC LIMIT ?"; params.append(min(1000, limite))
        return {"itens": [dict(r) for r in hz.db.query(sql, params)]}

    # ------------------------------------------------------------ painel
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    return app


def _simple_page(title: str, message: str, back: bool = True) -> str:
    from html import escape

    link = '<p><a href="/#linkedin">Voltar ao painel</a></p>' if back else ""
    return (f"<!doctype html><meta charset='utf-8'><title>{escape(title)}</title>"
            "<body style='font-family:system-ui;background:#0b1220;color:#e7ecf4;display:grid;place-items:center;min-height:100vh;margin:0'>"
            f"<main style='max-width:520px;padding:24px'><h1 style='font-weight:600'>{escape(title)}</h1>"
            f"<p>{escape(message)}</p>{link}</main></body>")
