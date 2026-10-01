"""SQLite storage for users and conversations."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

import bcrypt

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    api_messages TEXT NOT NULL DEFAULT '[]',  -- exact message list sent to Claude
    ui_messages  TEXT NOT NULL DEFAULT '[]',  -- what the browser renders (text, charts, tables)
    state        TEXT NOT NULL DEFAULT '{}',  -- working set: portfolio TINs, target MLR, etc.
    busy_token   TEXT,                        -- turn lock: set while a question is being answered
    busy_until   REAL,                        -- ...and when that lock expires if its holder died
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(username, updated_at DESC);
CREATE TABLE IF NOT EXISTS usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,
    conversation_id TEXT,
    ts            REAL NOT NULL,
    model         TEXT NOT NULL,
    provider      TEXT NOT NULL,
    kind          TEXT NOT NULL,            -- chat | summary
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    rate_known    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage(username, ts);
CREATE INDEX IF NOT EXISTS idx_usage_conv ON usage(conversation_id);
CREATE TABLE IF NOT EXISTS login_attempts (   -- sign-in attempts that have not (yet) succeeded, for the lockout
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ip  TEXT NOT NULL,
    ts  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_ip_ts ON login_attempts(ip, ts);
CREATE INDEX IF NOT EXISTS idx_login_ts ON login_attempts(ts);
"""


@contextmanager
def db():
    con = sqlite3.connect(config.APP_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with db() as con:
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(conversations)")}
        if "state" not in cols:  # upgrade databases created before the working set existed
            con.execute("ALTER TABLE conversations ADD COLUMN state TEXT NOT NULL DEFAULT '{}'")
        if "busy_token" not in cols:  # ...and before the turn lock
            con.execute("ALTER TABLE conversations ADD COLUMN busy_token TEXT")
            con.execute("ALTER TABLE conversations ADD COLUMN busy_until REAL")


# ---- users ---------------------------------------------------------------
def upsert_user(username: str, password: str, display_name: str | None = None, is_admin: bool = False) -> None:
    pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with db() as con:
        con.execute(
            "INSERT INTO users (username, display_name, password_hash, is_admin, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, "
            "display_name=excluded.display_name, is_admin=excluded.is_admin",
            (username.lower(), display_name or username, pw, int(is_admin), time.time()))


def delete_user(username: str) -> bool:
    with db() as con:
        return con.execute("DELETE FROM users WHERE username=?", (username.lower(),)).rowcount > 0


def list_users() -> list[dict]:
    with db() as con:
        return [dict(r) for r in con.execute("SELECT username, display_name, is_admin FROM users ORDER BY username")]


_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()


def verify_user(username: str, password: str) -> dict | None:
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username.lower(),)).fetchone()
    # Always run bcrypt so response time doesn't reveal whether the user exists.
    ok = bcrypt.checkpw(password.encode(), (row["password_hash"] if row else _DUMMY_HASH).encode())
    if row and ok:
        return {"username": row["username"], "display_name": row["display_name"], "is_admin": bool(row["is_admin"])}
    return None


def begin_login_attempt(ip: str, limit: int, window: float) -> bool:
    """Count a sign-in attempt from an address; False when the address is locked out (`limit` attempts that did
    not succeed within the last `window` seconds). The attempt is written before it is counted, in one
    transaction, so SQLite's write lock orders concurrent attempts from any number of worker processes: no more
    than `limit` can be let through, however many arrive at once. A refused attempt is not kept, so the lock
    lasts `window` seconds from the failures that caused it rather than being extended by retries."""
    now = time.time()
    with db() as con:
        con.execute("DELETE FROM login_attempts WHERE ts < ?", (now - window,))
        row = con.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, now)).lastrowid
        recent = con.execute("SELECT count(*) FROM login_attempts WHERE ip = ? AND ts >= ?", (ip, now - window)).fetchone()[0]
        if recent > limit:
            con.execute("DELETE FROM login_attempts WHERE id = ?", (row,))
            return False
    return True


def clear_login_attempts(ip: str) -> None:
    """A successful sign-in wipes the address's count."""
    with db() as con:
        con.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))


def get_user(username: str) -> dict | None:
    with db() as con:
        row = con.execute("SELECT username, display_name, is_admin FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


# ---- conversations -------------------------------------------------------
def create_conversation(username: str, title: str, state: dict | None = None) -> str:
    cid = uuid.uuid4().hex
    now = time.time()
    with db() as con:
        con.execute("INSERT INTO conversations (id, username, title, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (cid, username, title, json.dumps(state or {}), now, now))
    return cid


def list_conversations(username: str) -> list[dict]:
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, title, updated_at, state FROM conversations WHERE username=? ORDER BY updated_at DESC LIMIT 200",
            (username,))]
    for r in rows:
        try:
            r["program"] = json.loads(r.pop("state") or "{}").get("program")
        except json.JSONDecodeError:
            r["program"] = None
    return rows


def get_conversation(username: str, cid: str) -> dict | None:
    with db() as con:
        row = con.execute("SELECT * FROM conversations WHERE id=? AND username=?", (cid, username)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["api_messages"] = json.loads(d["api_messages"])
    d["ui_messages"] = json.loads(d["ui_messages"])
    d["state"] = json.loads(d["state"] or "{}")
    return d


def acquire_turn(username: str, cid: str, ttl: float) -> str | None:
    """Take the conversation's turn lock: one question at a time per chat. Returns a token, or None while
    another request holds the lock. It is a single UPDATE in the shared database, so it holds across worker
    processes as well as within one; it expires after `ttl` seconds so a holder that died does not block the
    chat for good. A turn reads the transcript only after taking the lock and saves it with the token."""
    token, now = uuid.uuid4().hex, time.time()
    with db() as con:
        taken = con.execute(
            "UPDATE conversations SET busy_token=?, busy_until=? WHERE id=? AND username=? "
            "AND (busy_until IS NULL OR busy_until < ?)", (token, now + ttl, cid, username, now)).rowcount
    return token if taken else None


def extend_turn(username: str, cid: str, token: str, ttl: float) -> None:
    """Keep the lock alive while a long answer is still making progress."""
    with db() as con:
        con.execute("UPDATE conversations SET busy_until=? WHERE id=? AND username=? AND busy_token=?",
                    (time.time() + ttl, cid, username, token))


def save_conversation(username: str, cid: str, api_messages: list, ui_messages: list, state: dict | None = None,
                      token: str | None = None) -> bool:
    """Store the transcript. With a turn token the write happens, and the lock is released, only if that
    turn still holds the lock; a turn whose lock expired and was taken by another returns False and writes
    nothing, so it cannot overwrite the newer transcript."""
    values = (json.dumps(api_messages), json.dumps(ui_messages), json.dumps(state or {}), time.time(), cid, username)
    with db() as con:
        if token is None:
            return con.execute("UPDATE conversations SET api_messages=?, ui_messages=?, state=?, updated_at=? "
                               "WHERE id=? AND username=?", values).rowcount > 0
        return con.execute("UPDATE conversations SET api_messages=?, ui_messages=?, state=?, updated_at=?, "
                           "busy_token=NULL, busy_until=NULL WHERE id=? AND username=? AND busy_token=?",
                           values + (token,)).rowcount > 0


def rename_conversation(username: str, cid: str, title: str) -> None:
    with db() as con:
        con.execute("UPDATE conversations SET title=? WHERE id=? AND username=?", (title[:120], cid, username))


def delete_conversation(username: str, cid: str) -> None:
    with db() as con:
        con.execute("DELETE FROM conversations WHERE id=? AND username=?", (cid, username))


# ---- usage / spend -------------------------------------------------------
def record_usage(username: str, conversation_id: str | None, model: str, provider: str, kind: str,
                 input_tokens: int, output_tokens: int, cache_write_tokens: int, cache_read_tokens: int,
                 cost_usd: float, rate_known: bool) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO usage (username, conversation_id, ts, model, provider, kind, input_tokens, output_tokens, "
            "cache_write_tokens, cache_read_tokens, cost_usd, rate_known) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, conversation_id, time.time(), model, provider, kind, input_tokens, output_tokens,
             cache_write_tokens, cache_read_tokens, cost_usd, int(rate_known)))


_SUM = ("count(*) AS requests, coalesce(sum(input_tokens),0) AS input_tokens, coalesce(sum(output_tokens),0) AS output_tokens, "
        "coalesce(sum(cache_write_tokens),0) AS cache_write_tokens, coalesce(sum(cache_read_tokens),0) AS cache_read_tokens, "
        "coalesce(sum(cost_usd),0) AS cost_usd, coalesce(sum(1 - rate_known),0) AS unpriced_requests")


def _period_starts() -> dict[str, float]:
    import datetime as _dt
    now = _dt.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    return {"today": today.timestamp(), "month": month.timestamp(), "all_time": 0.0}


def usage_summary(username: str, conversation_id: str | None = None) -> dict:
    out: dict = {"periods": {}, "by_model": [], "recent_chats": []}
    with db() as con:
        for name, start in _period_starts().items():
            r = con.execute(f"SELECT {_SUM} FROM usage WHERE username=? AND ts>=?", (username, start)).fetchone()
            out["periods"][name] = _row(r)
        if conversation_id:
            r = con.execute(f"SELECT {_SUM} FROM usage WHERE username=? AND conversation_id=?", (username, conversation_id)).fetchone()
            out["periods"]["this_chat"] = _row(r)
        out["by_model"] = [dict(_row(r), model=r["model"], provider=r["provider"]) for r in con.execute(
            f"SELECT model, provider, {_SUM} FROM usage WHERE username=? GROUP BY model, provider ORDER BY cost_usd DESC", (username,))]
        out["recent_chats"] = [dict(_row(r), conversation_id=r["conversation_id"], title=r["title"]) for r in con.execute(
            f"SELECT u.conversation_id, c.title, {_SUM} FROM usage u LEFT JOIN conversations c ON c.id=u.conversation_id "
            f"WHERE u.username=? GROUP BY u.conversation_id ORDER BY max(u.ts) DESC LIMIT 10", (username,))]
    return out


def usage_all_users() -> list[dict]:
    starts = _period_starts()
    with db() as con:
        rows = {r["username"]: dict(_row(r), username=r["username"], display_name=r["display_name"]) for r in con.execute(
            f"SELECT u.username, us.display_name, {_SUM} FROM usage u LEFT JOIN users us ON us.username=u.username "
            f"GROUP BY u.username ORDER BY cost_usd DESC")}
        for r in con.execute(f"SELECT username, {_SUM} FROM usage WHERE ts>=? GROUP BY username", (starts["month"],)):
            if r["username"] in rows:
                rows[r["username"]]["month"] = _row(r)
        for r in con.execute(f"SELECT username, {_SUM} FROM usage WHERE ts>=? GROUP BY username", (starts["today"],)):
            if r["username"] in rows:
                rows[r["username"]]["today"] = _row(r)
    return list(rows.values())


def _row(r) -> dict:
    d = {k: r[k] for k in ("requests", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "cost_usd", "unpriced_requests")}
    d["total_tokens"] = d["input_tokens"] + d["output_tokens"] + d["cache_write_tokens"] + d["cache_read_tokens"]
    d["cost_usd"] = round(d["cost_usd"], 4)
    return d
