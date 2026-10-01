"""FastAPI app: login, conversation history, and the streaming chat endpoint."""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, pricing, store
from .agent import Agent, repair_history
from .data import Warehouse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC = config.BASE_DIR / "static"
COOKIE = "session"
runtime: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    wh = Warehouse.open()
    runtime["wh"] = wh
    runtime["agent"] = Agent(wh)
    log.info("Ready (app version %s): %s", config.APP_VERSION, ", ".join(f"{t} ({i['rows']:,} rows)" for t, i in wh.tables.items()))
    if config.CLAUDE_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY is not set — chat requests will fail until it is "
                    "(or set CLAUDE_PROVIDER=foundry with the Foundry variables).")
    if not store.list_users():
        log.warning("No users yet. Create one:  python -m scripts.manage_users add <username>")
    yield


class RevalidatedStatic(StaticFiles):
    """Static files that the browser re-checks on every load (ETag → 304), so a deploy is never masked by a cached app.js."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", RevalidatedStatic(directory=STATIC), name="static")


# ---------------------------------------------------------------- auth ----
def _issue(resp: Response, username: str) -> None:
    token = jwt.encode({"sub": username, "exp": int(time.time()) + config.SESSION_HOURS * 3600},
                       config.SECRET_KEY, algorithm="HS256")
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                    max_age=config.SESSION_HOURS * 3600)


def _session_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        sub = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None
    return store.get_user(sub)


def current_user(request: Request) -> dict:
    user = _session_user(request)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


_failed: dict[str, list[float]] = defaultdict(list)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    _failed[ip] = [t for t in _failed[ip] if now - t < 900]
    if len(_failed[ip]) >= 8:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    user = store.verify_user(body.username.strip(), body.password)
    if not user:
        _failed[ip].append(now)
        raise HTTPException(401, "Incorrect username or password")
    _failed.pop(ip, None)
    _issue(response, user["username"])
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


# --------------------------------------------------------------- pages ----
@app.get("/")
def index(request: Request):
    if not _session_user(request):
        return RedirectResponse("/login")
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def public_config():
    return {"app_name": config.APP_NAME}


def _suggestions(program: str) -> list[str]:
    for name in (f"suggestions-{program.lower()}.txt", "suggestions.txt"):
        f = config.DATA_DIR / name
        if f.exists():
            return [s.strip() for s in f.read_text(encoding="utf-8").splitlines() if s.strip()][:4]
    return []


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    wh: Warehouse = runtime["wh"]
    programs = [{"id": p["id"], "label": p["label"], "description": p["description"], "rows": p["rows"],
                 "columns": p["columns"], "sources": p["sources"], "suggestions": _suggestions(p["id"])}
                for p in wh.programs.values()]
    return {"user": user, "app_name": config.APP_NAME, "programs": programs}


# ------------------------------------------------------- conversations ----
@app.get("/api/conversations")
def conversations(user: dict = Depends(current_user)):
    return store.list_conversations(user["username"])


@app.get("/api/conversations/{cid}")
def conversation(cid: str, user: dict = Depends(current_user)):
    c = store.get_conversation(user["username"], cid)
    if not c:
        raise HTTPException(404)
    return {"id": c["id"], "title": c["title"], "messages": c["ui_messages"], "state": c.get("state") or {}}


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.patch("/api/conversations/{cid}")
def rename(cid: str, body: RenameIn, user: dict = Depends(current_user)):
    store.rename_conversation(user["username"], cid, body.title)
    return {"ok": True}


@app.delete("/api/conversations/{cid}")
def delete(cid: str, user: dict = Depends(current_user)):
    store.delete_conversation(user["username"], cid)
    return {"ok": True}


# --------------------------------------------------------------- usage ----
@app.get("/api/usage")
def usage(conversation_id: str | None = None, user: dict = Depends(current_user)):
    summary = store.usage_summary(user["username"], conversation_id)
    summary["rate_card"] = pricing.rate_card([m["model"] for m in summary["by_model"]] or [config.ANTHROPIC_MODEL])
    summary["provider"] = config.CLAUDE_PROVIDER
    summary["app_version"] = config.APP_VERSION
    summary["note"] = ("Estimated from the token counts returned by each model call, priced at Anthropic list prices"
                       + (f" × {config.PRICE_MULTIPLIER:g}" if config.PRICE_MULTIPLIER != 1 else "")
                       + ". Your invoice is authoritative.")
    if user.get("is_admin"):
        summary["all_users"] = store.usage_all_users()
    return summary


# ---------------------------------------------------------------- chat ----
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    program: str | None = None   # required on the first message when more than one dataset is loaded


_busy: set[str] = set()


@app.post("/api/chat")
async def chat(body: ChatIn, user: dict = Depends(current_user)):
    uname = user["username"]
    if body.conversation_id:
        conv = store.get_conversation(uname, body.conversation_id)
        if not conv:
            raise HTTPException(404)
    else:
        programs = runtime["wh"].programs
        program = body.program if body.program in programs else (next(iter(programs)) if len(programs) == 1 else None)
        if not program:
            raise HTTPException(400, "Choose a dataset (program) before starting a new chat.")
        title = " ".join(body.message.split())[:70]
        cid = store.create_conversation(uname, title, {"program": program})
        conv = store.get_conversation(uname, cid)
    cid = conv["id"]
    if cid in _busy:
        raise HTTPException(409, "This chat is still answering the previous question.")

    api_msgs = repair_history(conv["api_messages"])
    ui_msgs = conv["ui_messages"]
    state = conv.get("state") or {}
    ui_msgs.append({"role": "user", "text": body.message})
    assistant = {"role": "assistant", "blocks": []}
    ui_msgs.append(assistant)
    agent: Agent = runtime["agent"]

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, default=str)}\n\n"

    async def stream():
        _busy.add(cid)
        blocks = assistant["blocks"]
        turn = {"calls": 0, "tokens": 0, "cost_usd": 0.0, "unpriced": False}
        try:
            yield sse({"type": "conversation", "id": cid, "title": conv["title"], "program": state.get("program")})
            async for ev in agent.run(api_msgs, body.message, state):
                if ev["type"] == "text":
                    if not blocks or blocks[-1]["type"] != "text":
                        blocks.append({"type": "text", "text": ""})
                    blocks[-1]["text"] += ev["text"]
                elif ev["type"] == "block":
                    blocks.append(ev["block"])
                elif ev["type"] == "usage":
                    cost, known = pricing.cost_usd(ev["model"], ev["input"], ev["output"], ev["cache_write"], ev["cache_read"])
                    store.record_usage(uname, cid, ev["model"], config.CLAUDE_PROVIDER, ev["kind"], ev["input"], ev["output"],
                                       ev["cache_write"], ev["cache_read"], cost, known)
                    turn["calls"] += 1
                    turn["tokens"] += ev["input"] + ev["output"] + ev["cache_write"] + ev["cache_read"]
                    turn["cost_usd"] += cost
                    turn["unpriced"] = turn["unpriced"] or not known
                    continue
                yield sse(ev)
            if turn["calls"]:
                ub = {"type": "usage", "calls": turn["calls"], "tokens": turn["tokens"],
                      "cost_usd": round(turn["cost_usd"], 4), "unpriced": turn["unpriced"]}
                blocks.append(ub)
                yield sse({"type": "block", "block": ub})
            yield sse({"type": "state", "state": state})
        except Exception as e:
            log.exception("chat failed")
            msg = _friendly_error(e)
            blocks.append({"type": "error", "text": msg})
            yield sse({"type": "error", "message": msg})
        finally:
            _busy.discard(cid)
            store.save_conversation(uname, cid, repair_history(api_msgs) if blocks and blocks[-1]["type"] == "error"
                                    else api_msgs, ui_msgs, state)
        yield sse({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _friendly_error(e: Exception) -> str:
    name = type(e).__name__
    if name == "AuthenticationError":
        if config.CLAUDE_PROVIDER == "foundry":
            return ("Authentication with Microsoft Foundry failed. Ask the administrator to check ANTHROPIC_FOUNDRY_API_KEY / "
                    "the Entra ID role (Foundry User) and the resource name.")
        return "The server's Claude API key is missing or invalid. Ask the administrator to check ANTHROPIC_API_KEY."
    if name == "NotFoundError":
        return (f"The model deployment '{config.ANTHROPIC_MODEL}' was not found. On Foundry, ANTHROPIC_MODEL must be the "
                f"deployment name shown in the Foundry portal.")
    if name == "PermissionDeniedError":
        return "Access to the model was denied (403). Check the Azure RBAC role on the Foundry resource."
    if name == "RateLimitError":
        return "Claude is rate-limited right now. Wait a moment and try again."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Couldn't reach Claude. Check the server's internet connection and try again."
    if name in ("OverloadedError", "InternalServerError"):
        return "Claude is temporarily overloaded. Try again in a minute."
    return f"Something went wrong ({name}). Try again."
