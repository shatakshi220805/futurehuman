# Futurehuman — project guide for Claude Code

Personal AI that builds a private memory of the user's screen, meetings and apps, then answers, drafts and alerts.
Brand colours: Jet Black #0B0B0B, Hot Pink #FF2DA8, Chartreuse #D4FF3F. Tone: professional, calm.

## Layout
- `backend/app/core.py` — all logic, stdlib only (SQLite + FTS5): auth, memories, links, hybrid search (BM25 + hashed-vector cosine), extraction, meetings, alert scoring, morning brief, rate limiter.
- `backend/app/main.py` — thin FastAPI layer (REST `/api/*`, WebSockets `/ws/meeting/{id}`, `/ws/live`), serves `frontend/`.
- `frontend/index.html` landing page; `frontend/app.html` the app (single file, no build step).
- `backend/tests/test_core.py` — unit tests for core (run: `cd backend && python -m unittest tests.test_core`).
- Deploy: `Dockerfile`, `docker-compose.yml`, `render.yaml`. Env vars in `.env.example`.

## Rules
- Put logic in `core.py` and test it; keep `main.py` thin. Run the tests before every commit.
- Privacy promises must stay true: no screenshots uploaded or stored (OCR runs in the browser), never auto-send email, user can edit/outdate/delete any memory, every query is scoped to the user's `uid`.
- Never commit `.env`, databases or tokens. Do not claim features the code lacks (the landing page must stay honest).
- Blueprint alert formula: score = relevance × urgency × confidence ÷ overhead, notify at ≥ `FH_THRESHOLD` (0.78).

## Roadmap (not built yet)
1. Gmail + Google Calendar read-only OAuth sync into memories; Gmail *draft* creation only (never send).
2. Server-side streaming transcription (Deepgram/Whisper) with speaker diarisation on `/ws/meeting`.
3. Tauri (Rust) desktop shell: global double-tap hotkey, screen-diff OCR (Apple Vision / Windows OCR), loopback audio, overlay HUD.
4. Storage adapters: Postgres, Qdrant (vectors), Neo4j (graph) behind the existing functions in `core.py`.
5. Real embedding model replacing `embed()`; LLM answer synthesis with citations when `ANTHROPIC_API_KEY` is set.
