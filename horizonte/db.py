"""Banco de dados SQLite do HORIZONTE (histórico persistente, sem servidor)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    org TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('primaria','publica','imprensa')),
    group_name TEXT NOT NULL CHECK (group_name IN ('juridica','politica','jornalistica')),
    homepage TEXT NOT NULL,
    feed_url TEXT,
    category_hint TEXT,
    region TEXT NOT NULL DEFAULT 'BR',
    image_policy TEXT NOT NULL DEFAULT 'nao_liberada',
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    etag TEXT,
    last_modified TEXT,
    last_checked TEXT,
    last_status TEXT,
    last_error TEXT,
    items_total INTEGER NOT NULL DEFAULT 0,
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL,
    url_canon TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    title_norm TEXT NOT NULL,
    summary TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    category TEXT,
    category_scores TEXT,
    region TEXT,
    relevance INTEGER NOT NULL DEFAULT 0,
    flags TEXT NOT NULL DEFAULT '[]',
    image_url TEXT,
    cluster_id INTEGER REFERENCES clusters(id),
    is_update INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_news_fetched ON news(fetched_at);
CREATE INDEX IF NOT EXISTS idx_news_cluster ON news(cluster_id);
CREATE INDEX IF NOT EXISTS idx_news_title ON news(title_norm);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    tokens TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT,
    region TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    newest_published TEXT,
    n_items INTEGER NOT NULL DEFAULT 1,
    n_orgs INTEGER NOT NULL DEFAULT 1,
    has_primary INTEGER NOT NULL DEFAULT 0,
    verification TEXT NOT NULL DEFAULT 'EM CONFERÊNCIA',
    verification_notes TEXT NOT NULL DEFAULT '[]',
    flags TEXT NOT NULL DEFAULT '[]',
    score INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clusters_last ON clusters(last_seen);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL UNIQUE REFERENCES clusters(id),
    day TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    analysis TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stories_day ON stories(day);

CREATE TABLE IF NOT EXISTS story_events (
    id INTEGER PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES stories(id),
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    story_id INTEGER REFERENCES stories(id),
    network TEXT NOT NULL CHECK (network IN ('linkedin','x')),
    format TEXT NOT NULL DEFAULT 'post',
    title TEXT,
    body TEXT NOT NULL,
    thread TEXT,
    hashtags TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    image TEXT,
    category TEXT,
    news_date TEXT,
    status TEXT NOT NULL,
    scheduled_for TEXT,
    published_at TEXT,
    external_id TEXT,
    external_url TEXT,
    error TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (network, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(network, status);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('diario','semanal','mensal')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (kind, period_start)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    job TEXT NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    details TEXT,
    UNIQUE (job, slot)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    module TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);

CREATE TABLE IF NOT EXISTS tokens (
    provider TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Database:
    """Conexão por thread, com WAL para leitura e escrita simultâneas."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.migrate()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transação de escrita serializada."""
        with self._write_lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        return self._conn().execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        return self._conn().execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.tx() as conn:
            return conn.execute(sql, params)

    def migrate(self) -> None:
        conn = self._conn()
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    # ---------- preferências ----------
    def get_pref(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return default if row is None else loads(row["value"], default)

    def set_pref(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, dumps(value)),
        )

    def prefs(self, defaults: dict) -> dict:
        stored = {r["key"]: loads(r["value"]) for r in self.query("SELECT key, value FROM settings")}
        merged = dict(defaults)
        merged.update({k: v for k, v in stored.items() if k in defaults})
        return merged

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def row_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for f in json_fields:
        if f in out:
            out[f] = loads(out[f], [] if f not in ("analysis", "image", "data") else None)
    return out
