import asyncio, os, json
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import core

app = FastAPI(title="Futurehuman API", version="1.1")
_api = core.RateLimiter(int(os.environ.get("FH_RATE", "120"))); _auth = core.RateLimiter(30)
@app.middleware("http")
async def limit(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/"):
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()) or (request.client.host if request.client else "?")
        if not (_auth.allow(ip + "a") if p.startswith("/api/auth/") else _api.allow(ip)): return JSONResponse({"detail": "Too many requests"}, status_code=429)
    r = await call_next(request); r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["Referrer-Policy"] = "same-origin"; return r
class Cred(BaseModel): email: str; password: str
class Cap(BaseModel): text: str; app: str = "Screen"; window: str = ""; project: Optional[str] = None; people: Optional[list[str]] = None
class MemIn(BaseModel): content: str; app: str = "Manual"; project: Optional[str] = None; people: Optional[list[str]] = None; due: Optional[float] = None
class MemUp(BaseModel): content: Optional[str] = None; status: Optional[str] = None; project: Optional[str] = None
class Q(BaseModel): q: str
class Mt(BaseModel): title: str = "Meeting"; project: Optional[str] = None
class Chunk(BaseModel): speaker: str = "Speaker"; text: str

def user(authorization: str = Header(None)):
    uid = core.check_token((authorization or "").replace("Bearer ", ""))
    if not uid: raise HTTPException(401, "Not authenticated")
    return uid
def guard(fn, *a):
    try: return fn(*a)
    except ValueError as e: raise HTTPException(400, str(e))

@app.get("/healthz")
def health(): return {"ok": True}
@app.post("/api/auth/register")
def reg(c: Cred): uid = guard(core.register, c.email, c.password); return {"token": core.make_token(uid)}
@app.post("/api/auth/login")
def log(c: Cred): uid = guard(core.login, c.email, c.password); return {"token": core.make_token(uid)}
@app.post("/api/capture")  # text from on-device OCR; screenshots never reach the server
def capture(c: Cap, u=Depends(user)): return guard(core.add_memory, u, c.text, c.app, c.window, c.project, c.people, None, "screen")
@app.post("/api/memories")
def mk(m: MemIn, u=Depends(user)): return guard(core.add_memory, u, m.content, m.app, "", m.project, m.people, m.due)
@app.get("/api/memories")
def ls(app_: Optional[str] = Query(None, alias="app"), person: str = None, project: str = None, days: int = 0, u=Depends(user)): return core.timeline(u, app_, person, project, days)
@app.patch("/api/memories/{mid}")
def up(mid: int, m: MemUp, u=Depends(user)):
    r = core.update(u, mid, m.content, m.status, m.project)
    if not r: raise HTTPException(404, "Not found")
    return r
@app.delete("/api/memories/{mid}")
def rm(mid: int, u=Depends(user)):
    if not core.delete(u, mid): raise HTTPException(404, "Not found")
    return {"deleted": mid}
@app.post("/api/ask")
def ask(q: Q, u=Depends(user)): return core.ask(u, q.q)
@app.get("/api/brief/{person}")
def brief(person: str, u=Depends(user)): return core.brief(u, person)
@app.post("/api/draft/{person}")
def draft(person: str, u=Depends(user)): return core.draft_email(u, person)
@app.get("/api/alerts")
def alerts(goal: str = None, focus: float = 0.3, threshold: float = None, u=Depends(user)): return core.candidates(u, goal, focus, threshold)
@app.post("/api/alerts/{mid}/dismiss")
def dis(mid: int, u=Depends(user)): core.dismiss(u, mid); return {"ok": True}
@app.post("/api/alerts/{mid}/act")
def act(mid: int, u=Depends(user)): core.act(u, mid); return {"ok": True}
@app.get("/api/routines/morning")
def morning(u=Depends(user)): return core.morning_brief(u)
@app.post("/api/meetings")
def mstart(m: Mt, u=Depends(user)): return {"id": core.start_meeting(u, m.title, m.project)}
@app.post("/api/meetings/{mid}/chunk")
def mchunk(mid: int, c: Chunk, u=Depends(user)): return guard(core.meeting_chunk, u, mid, c.speaker, c.text)
@app.post("/api/meetings/{mid}/finish")
def mfin(mid: int, u=Depends(user)): return guard(core.finish_meeting, u, mid)

@app.websocket("/ws/meeting/{mid}")  # streaming transcript in, live commitments out
async def ws_meeting(ws: WebSocket, mid: int, token: str):
    uid = core.check_token(token)
    if not uid: await ws.close(4401); return
    await ws.accept()
    try:
        while True:
            d = json.loads(await ws.receive_text())
            await ws.send_json({"type": "chunk", **core.meeting_chunk(uid, mid, d.get("speaker", "Speaker"), d.get("text", ""))})
    except (WebSocketDisconnect, ValueError): pass

@app.websocket("/ws/live")  # proactive interventions pushed when score >= threshold
async def ws_live(ws: WebSocket, token: str, goal: str = None):
    uid = core.check_token(token)
    if not uid: await ws.close(4401); return
    await ws.accept(); sent = set()
    try:
        while True:
            for c in core.candidates(uid, goal):
                if c["notify"] and c["memory"]["id"] not in sent: sent.add(c["memory"]["id"]); await ws.send_json(c)
            await asyncio.sleep(20)
    except WebSocketDisconnect: pass

if os.path.isdir("frontend"): app.mount("/", StaticFiles(directory="frontend", html=True), name="web")
