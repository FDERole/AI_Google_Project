"""Sanjaya web server: REST for posts and actions, a WebSocket for the live group chat."""
import json
import logging
import mimetypes
import uuid
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DATA_DIR, STATIC_DIR, UPLOAD_DIR
from .engine import Engine

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Sanjaya")
engine = Engine()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEMO_MEDIA = json.loads((DATA_DIR / "demo_media.json").read_text(encoding="utf-8"))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/media/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/media/demo", StaticFiles(directory=DATA_DIR / "demo_media"), name="demo")
app.mount("/media/datasheets", StaticFiles(directory=DATA_DIR / "datasheets"), name="datasheets")


def _kind_for(mime):
    if mime.startswith("audio/"):
        return "voice"
    if mime.startswith("image/"):
        return "photo"
    return "document"


def _user_or_404(user_id):
    if not engine.plant.user(user_id):
        raise HTTPException(404, f"Unknown user {user_id}")
    return user_id


def _demo_attachment(ref):
    """'demo:alarm_panel_muted.png' or 'datasheet:kestrel_kx120.pdf' -> attachment dict."""
    prefix, _, name = ref.partition(":")
    if prefix == "demo" and name in DEMO_MEDIA:
        path = DATA_DIR / "demo_media" / name
        return {"kind": "photo", "path": path, "mime": "image/png", "name": name,
                "url": f"/media/demo/{name}", "demo_meta": DEMO_MEDIA[name]}
    if prefix == "datasheet" and (DATA_DIR / "datasheets" / name).is_file() and name.endswith(".pdf"):
        path = DATA_DIR / "datasheets" / name
        return {"kind": "document", "path": path, "mime": "application/pdf", "name": name,
                "url": f"/media/datasheets/{name}"}
    raise HTTPException(400, f"Unknown demo attachment {ref}")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": engine.brain.mode}


@app.get("/api/bootstrap")
def bootstrap():
    return {
        "plant": engine.plant.info,
        "users": list(engine.plant.users.values()),
        "messages": engine.messages,
        "dashboard": engine.snapshot(),
    }


@app.websocket("/ws")
async def ws(websocket: WebSocket, user: str = "dashboard"):
    await websocket.accept()
    engine.clients[websocket] = user
    try:
        while True:
            await websocket.receive_text()  # keep-alive pings from the client
    except WebSocketDisconnect:
        pass
    finally:
        engine.clients.pop(websocket, None)


@app.post("/api/messages")
async def post_message(
    user: str = Form(...),
    text: str = Form(""),
    transcript: Optional[str] = Form(None),
    reply_to: Optional[str] = Form(None),
    as_voice: bool = Form(False),
    demo: str = Form(""),
    files: List[UploadFile] = File(default=[]),
):
    _user_or_404(user)
    attachments = []
    for f in files:
        if not f.filename:
            continue
        mime = f.content_type or mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
        base = mime.split(";")[0]
        ext = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a"}.get(base) or \
            mimetypes.guess_extension(base) or ""
        stored = f"{uuid.uuid4().hex}{ext}"
        data = await f.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, "File too large (15 MB max)")
        (UPLOAD_DIR / stored).write_bytes(data)
        attachments.append({"kind": _kind_for(mime), "path": UPLOAD_DIR / stored, "mime": mime.split(";")[0],
                            "name": f.filename, "url": f"/media/uploads/{stored}"})
    for ref in filter(None, (r.strip() for r in demo.split(","))):
        attachments.append(_demo_attachment(ref))
    if not text.strip() and not attachments and not transcript:
        raise HTTPException(400, "Empty message")
    msg = await engine.post(user, text.strip(), attachments, client_transcript=transcript,
                            reply_to=reply_to, as_voice=as_voice)
    return {"ok": True, "id": msg["id"]}


class DecisionIn(BaseModel):
    user: str
    decision: str
    max_minutes: Optional[int] = None
    conditions: Optional[str] = None


class UserIn(BaseModel):
    user: str


class ConfirmIn(BaseModel):
    user: str
    yes: bool


class SettingsIn(BaseModel):
    speed: Optional[float] = None
    offline: Optional[bool] = None


def _request_or_404(req_id):
    req = engine.requests.get(req_id)
    if not req:
        raise HTTPException(404, "Unknown request")
    return req


@app.post("/api/requests/{req_id}/decision")
async def decision(req_id: str, body: DecisionIn):
    req = _request_or_404(req_id)
    if body.decision not in ("approve", "approve_with_conditions", "reject"):
        raise HTTPException(400, "Bad decision")
    if body.user not in req["approvers"] or req["status"] != "pending":
        raise HTTPException(409, "You can't decide this request right now")
    await engine.decide(req, body.user, body.model_dump(exclude={"user"}), via="button")
    await engine.push_dashboard()
    return {"ok": True}


@app.post("/api/requests/{req_id}/confirm")
async def confirm(req_id: str, body: ConfirmIn):
    req = _request_or_404(req_id)
    await engine.confirm(req, body.user, body.yes, via="button")
    await engine.push_dashboard()
    return {"ok": True}


@app.post("/api/requests/{req_id}/start")
async def start(req_id: str, body: UserIn):
    await engine.start(_request_or_404(req_id), body.user)
    await engine.push_dashboard()
    return {"ok": True}


@app.post("/api/requests/{req_id}/finish")
async def finish(req_id: str, body: UserIn):
    await engine.finish(_request_or_404(req_id), body.user)
    await engine.push_dashboard()
    return {"ok": True}


@app.post("/api/requests/{req_id}/skip-wait")
async def skip_wait(req_id: str):
    _request_or_404(req_id)
    await engine.skip_wait(req_id)
    return {"ok": True}


@app.post("/api/changes/{change_id}/close")
async def close_change(change_id: str, body: UserIn):
    await engine.close_change(change_id, _user_or_404(body.user))
    return {"ok": True}


@app.post("/api/demo/reset")
async def reset():
    engine.reset()
    await engine.emit({"type": "reset"})
    return {"ok": True}


@app.post("/api/demo/settings")
async def settings(body: SettingsIn):
    if body.speed is not None:
        engine.speed = max(0.1, min(body.speed, 120))
    if body.offline is not None:
        engine.brain.force_offline = body.offline
    await engine.push_dashboard()
    return {"ok": True, "speed": engine.speed, "mode": engine.brain.mode}


@app.get("/api/audit")
def audit():
    return JSONResponse(engine.audit)
