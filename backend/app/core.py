"""Futurehuman core engine (stdlib only): memory store, graph links, extraction,
hybrid search, interruption scoring, meetings, briefs. FastAPI is a thin layer on top."""
import os, re, json, time, math, struct, sqlite3, hmac, hashlib, base64, secrets, urllib.request, datetime as dt

DB_PATH = os.environ.get("FH_DB", "futurehuman.db")
SECRET = os.environ.get("FH_SECRET", "dev-secret-change-me").encode()
THRESHOLD = float(os.environ.get("FH_THRESHOLD", "0.78"))
STOP = set("what was the did and for that about with have from since where which who whom find ask asked made when this them they there their been into your you our out how why can are not all any but".split())
NOT_NAMES = set("The This That Email Doc Let We You Our Hi Hello Monday Tuesday Wednesday Thursday Friday Saturday Sunday Next Please Thanks Docs Gmail Notion Slack Chrome Meeting Can Could".split())
DAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

_conns = {}
def db():
    c = _conns.get(DB_PATH)
    if c is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False); c.row_factory = sqlite3.Row
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, salt TEXT, pw TEXT);
        CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, uid INT, content TEXT, app TEXT, window TEXT,
          ts REAL, people TEXT, project TEXT, due REAL, conf REAL, status TEXT DEFAULT 'current', kind TEXT DEFAULT 'context',
          session INT, source TEXT, chash TEXT);
        CREATE INDEX IF NOT EXISTS mem_u ON memories(uid, ts);
        CREATE TABLE IF NOT EXISTS links(uid INT, a INT, b INT, rel TEXT, UNIQUE(a,b));
        CREATE TABLE IF NOT EXISTS dismissed(uid INT, mid INT, UNIQUE(uid,mid));
        CREATE TABLE IF NOT EXISTS meetings(id INTEGER PRIMARY KEY, uid INT, title TEXT, project TEXT, started REAL, ended REAL, summary TEXT);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, mid INT, speaker TEXT, text TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS vecs(mid INTEGER PRIMARY KEY, v BLOB);
        CREATE TABLE IF NOT EXISTS feedback(uid INT, mid INT, action TEXT, ts REAL);
        CREATE VIRTUAL TABLE IF NOT EXISTS mfts USING fts5(content, people, project, app);
        """)
        _conns[DB_PATH] = c
    return c

# ---------- auth ----------
def _hash(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
def register(email, pw):
    email = email.strip().lower()
    if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(pw) < 8: raise ValueError("Valid email and 8+ character password required")
    salt = secrets.token_hex(8)
    try: cur = db().execute("INSERT INTO users(email,salt,pw) VALUES(?,?,?)", (email, salt, _hash(pw, salt))); db().commit()
    except sqlite3.IntegrityError: raise ValueError("Email already registered")
    return cur.lastrowid
def login(email, pw):
    r = db().execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not r or not hmac.compare_digest(r["pw"], _hash(pw, r["salt"])): raise ValueError("Invalid credentials")
    return r["id"]
def make_token(uid, ttl=7*86400):
    p = base64.urlsafe_b64encode(json.dumps({"u": uid, "e": int(time.time()+ttl)}).encode()).decode()
    return p + "." + hmac.new(SECRET, p.encode(), hashlib.sha256).hexdigest()
def check_token(t):
    try:
        p, s = t.split(".")
        if not hmac.compare_digest(s, hmac.new(SECRET, p.encode(), hashlib.sha256).hexdigest()): return None
        d = json.loads(base64.urlsafe_b64decode(p)); return d["u"] if d["e"] > time.time() else None
    except Exception: return None

# ---------- extraction ----------
def parse_due(s, base=None):
    base = base or time.time(); s = (s or "").lower(); d0 = dt.datetime.fromtimestamp(base)
    end = lambda d: dt.datetime.combine(d.date(), dt.time(17, 0)).timestamp()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m: return dt.datetime(int(m[1]), int(m[2]), int(m[3]), 17).timestamp()
    if "tomorrow" in s: return end(d0 + dt.timedelta(days=1))
    if "today" in s or "tonight" in s: return end(d0)
    if "next week" in s: return end(d0 + dt.timedelta(days=7))
    m = re.search(r"in (\d+) days?", s)
    if m: return end(d0 + dt.timedelta(days=int(m[1])))
    for i, n in enumerate(DAYS):
        if n in s: return end(d0 + dt.timedelta(days=(i - d0.weekday()) % 7 or 7))
    return None

def find_people(text):
    out = []
    for p in (r"\b([A-Z][a-z]{2,})(?=\s+(?:will|asked|said|wants|needs|agreed|sent|shared|promised))", r"\b(?:from|with|to|ask|cc)\s+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)", r"^([A-Z][a-z]{2,}):"):
        for m in re.finditer(p, text, re.M):
            n = m.group(1)
            if n.split()[0] not in NOT_NAMES and n not in out: out.append(n)
    return out

def analyse(text, speaker=None, base=None):
    """Rule-based extraction. Explicit commitments are separated from tentative plans."""
    res = {"commitments": [], "tentative": [], "decisions": [], "questions": []}
    for s in [x.strip() for x in re.split(r"(?<=[.?!])\s+|\n", text) if x.strip()]:
        sp = speaker; m = re.match(r"^([A-Z][a-z]+):\s*(.*)$", s)
        if m: sp, s = m[1], m[2]
        if s.endswith("?"): res["questions"].append(s); continue
        if re.search(r"\b(we decided|decided|agreed|going with|we'll go with)\b", s, re.I): res["decisions"].append(s)
        c = re.match(r"^(?:I'll|I will)\s+(.+?)(?:\s+(?:by|before|on)\s+([\w ,-]+?))?[.!]?$", s, re.I)
        if c: who, what, dl = sp or "You", c[1], c[2]
        else:
            c = re.match(r"^([A-Z][a-z]+)\s+will\s+(.+?)(?:\s+(?:by|before|on)\s+([\w ,-]+?))?[.!]?$", s)
            who, what, dl = (c[1], c[2], c[3]) if c else (None, None, None)
        if who and who not in NOT_NAMES:
            res["commitments"].append({"who": who, "what": what, "deadline_text": dl, "due": parse_due(dl or what, base), "source": s}); continue
        if re.search(r"\b(let's|we could|maybe|might|perhaps|should)\b", s, re.I): res["tentative"].append(s)
    return res

def llm_extract(text):
    """Optional: structured extraction with Claude when ANTHROPIC_API_KEY is set."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    body = {"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 800,
            "messages": [{"role": "user", "content": "Return ONLY JSON {people:[],project:str|null,due_text:str|null} for this captured text:\n" + text[:4000]}]}
    try:
        rq = urllib.request.Request("https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
            {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        out = json.load(urllib.request.urlopen(rq, timeout=15))["content"][0]["text"]
        return json.loads(out[out.index("{"): out.rindex("}") + 1])
    except Exception: return None

# ---------- memory ----------
def _row(r):
    d = dict(r); d["people"] = json.loads(d["people"] or "[]"); d.pop("chash", None); d.pop("r", None); d.pop("vb", None)
    d["links"] = [x["b"] for x in db().execute("SELECT b FROM links WHERE a=?", (d["id"],))]; return d

def add_memory(uid, content, app="Manual", window="", project=None, people=None, due=None, kind="context", conf=0.85, ts=None, source=None):
    content = (content or "").strip(); ts = ts or time.time()
    if not content: raise ValueError("Empty content")
    h = hashlib.sha1((app + content).encode()).hexdigest()
    dup = db().execute("SELECT id FROM memories WHERE uid=? AND chash=? AND ts>?", (uid, h, ts - 3600)).fetchone()
    if dup: return get(uid, dup["id"])  # screen-delta dedupe
    ex = llm_extract(content) or {}
    people = people if people is not None else (ex.get("people") or find_people(content))
    project = project or ex.get("project")
    if due is None and re.search(r"\b(by|due|before|deadline)\b", content, re.I): due = parse_due(ex.get("due_text") or content, ts)
    last = db().execute("SELECT session, ts FROM memories WHERE uid=? ORDER BY ts DESC LIMIT 1", (uid,)).fetchone()
    sess = last["session"] if last and ts - last["ts"] < 600 else int(ts)
    cur = db().execute("INSERT INTO memories(uid,content,app,window,ts,people,project,due,conf,kind,session,source,chash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, content, app, window, ts, json.dumps(people), project, due, conf, kind, sess, source, h))
    mid = cur.lastrowid
    db().execute("INSERT INTO mfts(rowid,content,people,project,app) VALUES(?,?,?,?,?)", (mid, content, " ".join(people), project or "", app))
    _store_vec(mid, content + " " + " ".join(people) + " " + (project or ""))
    n = 0
    for r in db().execute("SELECT id,people,project FROM memories WHERE uid=? AND id!=? AND status='current' ORDER BY ts DESC LIMIT 200", (uid, mid)):
        if n < 4 and ((project and r["project"] == project) or set(people) & set(json.loads(r["people"] or "[]"))):
            for a, b in ((mid, r["id"]), (r["id"], mid)): db().execute("INSERT OR IGNORE INTO links VALUES(?,?,?,?)", (uid, a, b, "RELATED"))
            n += 1
    db().commit(); return get(uid, mid)

def get(uid, mid):
    r = db().execute("SELECT * FROM memories WHERE id=? AND uid=?", (mid, uid)).fetchone(); return _row(r) if r else None

def update(uid, mid, content=None, status=None, project=None):
    m = get(uid, mid)
    if not m: return None
    if content is not None:
        db().execute("UPDATE memories SET content=? WHERE id=?", (content, mid))
        db().execute("DELETE FROM mfts WHERE rowid=?", (mid,)); db().execute("INSERT INTO mfts(rowid,content,people,project,app) VALUES(?,?,?,?,?)", (mid, content, " ".join(m["people"]), m["project"] or "", m["app"])); _store_vec(mid, content + " " + " ".join(m["people"]))
    if status in ("current", "outdated"): db().execute("UPDATE memories SET status=? WHERE id=?", (status, mid))
    if project is not None: db().execute("UPDATE memories SET project=? WHERE id=?", (project, mid))
    db().commit(); return get(uid, mid)

def delete(uid, mid):
    if not get(uid, mid): return False
    db().execute("DELETE FROM memories WHERE id=?", (mid,)); db().execute("DELETE FROM mfts WHERE rowid=?", (mid,)); db().execute("DELETE FROM vecs WHERE mid=?", (mid,)); db().execute("DELETE FROM links WHERE a=? OR b=?", (mid, mid))
    db().commit(); return True

def timeline(uid, app=None, person=None, project=None, days=0, limit=300):
    rows = [_row(r) for r in db().execute("SELECT * FROM memories WHERE uid=? ORDER BY ts DESC LIMIT ?", (uid, limit))]
    cut = time.time() - days * 86400
    return [m for m in rows if (not app or m["app"] == app) and (not person or person in m["people"]) and (not project or m["project"] == project) and (not days or m["ts"] >= cut)]

# ---------- vectors (local hashed n-gram embeddings; swap for a hosted model/Qdrant later) ----------
EMB_DIM = 256
def embed(text, dim=EMB_DIM):
    v = [0.0] * dim
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if t in STOP: continue
        w = f"<{t}>"
        for g in [w[i:i + 3] for i in range(len(w) - 2)] + [t]:
            h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16); v[h % dim] += 1 if (h >> 8) & 1 else -1
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
def _blob(v): return struct.pack(f"{len(v)}f", *v)
def _store_vec(mid, text): db().execute("INSERT OR REPLACE INTO vecs VALUES(?,?)", (mid, _blob(embed(text))))
def _vsearch(uid, q, k):
    qv = embed(q)
    if not any(qv): return []
    sc = []
    for r in db().execute("SELECT m.*, v.v vb FROM memories m LEFT JOIN vecs v ON v.mid=m.id WHERE m.uid=? ORDER BY m.ts DESC LIMIT 2000", (uid,)).fetchall():
        vb = r["vb"] or _blob(embed(r["content"]))
        s = sum(a * b for a, b in zip(qv, struct.unpack(f"{len(vb)//4}f", vb)))
        if s > 0.25: sc.append((s, r))
    out = []
    for s, r in sorted(sc, key=lambda x: -x[0])[:k]:
        d = _row(r); d["via"] = "vector"; d["_s"] = s; out.append(d)
    return out
def _fts(uid, q, k):
    toks = [t for t in re.findall(r"[A-Za-z0-9]{3,}", q.lower()) if t not in STOP]
    if not toks: return []
    try: rows = db().execute("SELECT m.*, bm25(mfts) r FROM mfts JOIN memories m ON m.id=mfts.rowid WHERE mfts MATCH ? AND m.uid=? ORDER BY r LIMIT ?", (" OR ".join(f'"{t}"' for t in toks), uid, k)).fetchall()
    except sqlite3.OperationalError: return []
    out = []
    for r in rows: d = _row(r); d["via"] = "text"; d["_s"] = -r["r"]; out.append(d)
    return out
def search(uid, q, k=8):
    """Hybrid retrieval: normalised BM25 (70%) + vector cosine (30%), then graph expansion."""
    fused = {}; w = {"text": 0.7, "vector": 0.3}
    for lst in (_fts(uid, q, k * 2), _vsearch(uid, q, k * 2)):
        mx = max([d["_s"] for d in lst] or [1]) or 1
        for d in lst:
            f = fused.setdefault(d["id"], {**d, "score": 0.0})
            f["score"] += w[d["via"]] * (d["_s"] / mx if d["via"] == "text" else d["_s"])
            if f["via"] != d["via"]: f["via"] = "hybrid"
    for f in fused.values():
        f.pop("_s", None); f["score"] += 0.02 / (1 + (time.time() - f["ts"]) / 86400)
        if f["status"] == "outdated": f["score"] *= 0.4
        f["score"] = round(f["score"], 4)
    for top in sorted(fused.values(), key=lambda x: -x["score"])[:2]:
        for lid in top["links"]:
            n = get(uid, lid) if lid not in fused else None
            if n: n["score"] = round(top["score"] * 0.5, 4); n["via"] = "graph"; fused[lid] = n
    return sorted(fused.values(), key=lambda x: -x["score"])[:k]

def ask(uid, q):
    res = search(uid, q)
    if not res: return {"answer": "I couldn't find anything in memory about that yet.", "sources": [], "progress": None}
    top = res[0]; ans = f"{top['content']} [#{top['id']}, {top['app']}, {dt.date.fromtimestamp(top['ts']).isoformat()}]"
    prog = None
    if re.search(r"progress|since|so far|follow", q, re.I):
        after = [m for m in timeline(uid) if m["ts"] > top["ts"] and m["id"] != top["id"] and m["status"] == "current" and ((top["project"] and m["project"] == top["project"]) or set(m["people"]) & set(top["people"]))]
        sent = [m for m in after if re.search(r"\b(sent|submitted)\b", m["content"], re.I) and not re.search(r"not yet", m["content"], re.I)]
        prog = {"recorded": after, "verdict": "Completion recorded." if sent else ("Related work recorded, but no confirmation it was completed (inferred, unverified)." if after else "No related activity recorded.")}
    return {"answer": ans, "sources": res, "progress": prog}

# ---------- proactive ----------
def score(rel, urg, conf, overhead): return round(rel * urg * conf / max(overhead, 0.8), 3)  # blueprint formula
def learned_adjust(uid):
    """Lightweight on-device personalisation: many dismissals raise the interruption bar, acting on alerts lowers it."""
    rows = db().execute("SELECT action, count(*) c FROM feedback WHERE uid=? AND ts>? GROUP BY action", (uid, time.time() - 30 * 86400)).fetchall()
    n = {r["action"]: r["c"] for r in rows}; d, a = n.get("dismiss", 0), n.get("act", 0)
    return round(((d + 1) / (d + a + 2) - 0.5) * 1.0, 3)
def candidates(uid, goal=None, focus=0.3, threshold=None):
    th = THRESHOLD if threshold is None else threshold; now = time.time(); out = []
    dis = {r["mid"] for r in db().execute("SELECT mid FROM dismissed WHERE uid=?", (uid,))}; adj = learned_adjust(uid)
    for m in timeline(uid):
        if not m["due"] or m["status"] != "current" or m["due"] < now: continue
        rel = 0.6 if not goal else (1.0 if m["project"] == goal else 0.4)
        urg = max(0.0, min(1.0, 1 - (m["due"] - now) / (7 * 86400)))
        s = score(rel, urg, m["conf"], 1 + focus * 0.5 + adj)
        out.append({"memory": m, "score": s, "rel": rel, "urg": round(urg, 2), "known": m["id"] in dis, "notify": s >= th and m["id"] not in dis,
                    "action": "Draft a follow-up" if m["people"] else "Create a reminder"})
    return sorted(out, key=lambda x: -x["score"])
def dismiss(uid, mid): db().execute("INSERT OR IGNORE INTO dismissed VALUES(?,?)", (uid, mid)); db().execute("INSERT INTO feedback VALUES(?,?,?,?)", (uid, mid, "dismiss", time.time())); db().commit()
def act(uid, mid): db().execute("INSERT OR IGNORE INTO dismissed VALUES(?,?)", (uid, mid)); db().execute("INSERT INTO feedback VALUES(?,?,?,?)", (uid, mid, "act", time.time())); db().commit()

# ---------- meetings ----------
def start_meeting(uid, title, project=None):
    c = db().execute("INSERT INTO meetings(uid,title,project,started) VALUES(?,?,?,?)", (uid, title or "Meeting", project, time.time())); db().commit(); return c.lastrowid
def meeting_chunk(uid, mid, speaker, text):
    m = db().execute("SELECT * FROM meetings WHERE id=? AND uid=?", (mid, uid)).fetchone()
    if not m: raise ValueError("Unknown meeting")
    ts = time.time(); db().execute("INSERT INTO chunks(mid,speaker,text,ts) VALUES(?,?,?,?)", (mid, speaker, text, ts)); db().commit()
    a = analyse(text, speaker, ts); saved = []
    for c in a["commitments"]:
        saved.append(add_memory(uid, f"{c['who']} will {c['what']}" + (f" ({c['deadline_text']})" if c["deadline_text"] else "") + ".", "Meeting", m["title"], m["project"], [c["who"]] if c["who"] != "You" else [], c["due"], "commitment", 0.9, ts, f"meeting:{mid}"))
    for d in a["decisions"]: saved.append(add_memory(uid, "Decision: " + d, "Meeting", m["title"], m["project"], [], None, "decision", 0.85, ts, f"meeting:{mid}"))
    return {"analysis": a, "saved": saved}
def finish_meeting(uid, mid):
    m = db().execute("SELECT * FROM meetings WHERE id=? AND uid=?", (mid, uid)).fetchone()
    if not m: raise ValueError("Unknown meeting")
    ch = db().execute("SELECT * FROM chunks WHERE mid=? ORDER BY ts", (mid,)).fetchall(); a = analyse("\n".join(f"{c['speaker']}: {c['text']}" for c in ch))
    speakers = sorted({c["speaker"] for c in ch if c["speaker"]}); summary = {"title": m["title"], "speakers": speakers, **a, "words": sum(len(c["text"].split()) for c in ch)}
    db().execute("UPDATE meetings SET ended=?, summary=? WHERE id=?", (time.time(), json.dumps(summary), mid)); db().commit()
    add_memory(uid, f"Meeting “{m['title']}” summary: {len(a['commitments'])} commitments, {len(a['decisions'])} decisions, {len(a['questions'])} open questions.", "Meeting", m["title"], m["project"], speakers, None, "summary", 0.9, source=f"meeting:{mid}")
    return summary

# ---------- actions ----------
def brief(uid, person):
    ms = [m for m in timeline(uid, person=person) if m["status"] == "current"]; pj = sorted({m["project"] for m in ms if m["project"]})
    return {"person": person, "projects": pj, "conversations": ms[:5], "commitments": [m for m in ms if m["due"] or m["kind"] == "commitment"],
            "status": {p: next(m["content"] for m in ms if m["project"] == p) for p in pj},
            "questions": [f"Is “{m['content'][:70]}” on track?" for m in ms if m["due"]] or ["Anything pending from last time?"]}
def draft_email(uid, person):
    b = brief(uid, person); c = b["commitments"][0]["content"] if b["commitments"] else "our last conversation"
    c = re.sub(r"^Email from [^:]+: ", "", c)
    return {"subject": f"Following up — {b['projects'][0] if b['projects'] else 'our conversation'}", "body": f"Hi {person.split()[0]},\n\nFollowing up on: {c}\nI'll share the update shortly. Happy to walk through it on a call.\n\nBest", "note": "Review before sending. Futurehuman never sends automatically."}

# ---------- routines ----------
def morning_brief(uid):
    now = time.time(); ms = [m for m in timeline(uid) if m["status"] == "current"]; sec = {}
    for m in sorted([m for m in ms if m["due"]], key=lambda m: m["due"]):
        if m["due"] < now - 86400: continue
        sec.setdefault(m["project"] or "General", []).append({"id": m["id"], "text": m["content"], "due": m["due"], "overdue": m["due"] < now, "people": m["people"]})
    yday = [m for m in ms if now - m["ts"] < 86400]
    return {"date": dt.date.today().isoformat(), "sections": [{"project": k, "items": v} for k, v in sec.items()], "captured_last_24h": len(yday),
            "apps": sorted({m["app"] for m in yday})}

# ---------- rate limiting ----------
class RateLimiter:
    def __init__(self, limit, window=60): self.limit, self.window, self.h = limit, window, {}
    def allow(self, key):
        now = time.time(); q = [t for t in self.h.get(key, []) if now - t < self.window]
        ok = len(q) < self.limit
        if ok: q.append(now)
        self.h[key] = q; return ok
