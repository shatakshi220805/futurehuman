# Futurehuman
Personal AI that builds a searchable memory of your digital life. FastAPI backend + web client.

## Run
    cp .env.example .env   # set FH_SECRET
    docker compose up --build        # http://localhost:8000
Without Docker: `cd backend && pip install -r requirements.txt && cd .. && uvicorn app.main:app --app-dir backend --port 8000`
Test: `cd backend && python -m unittest tests.test_core`

## Push to GitHub
    git init && git add . && git commit -m "Futurehuman MVP"
    git branch -M main && git remote add origin https://github.com/shatakshi220805/futurehuman.git && git push -u origin main

## Deploy on Render (free plan, auto-deploys on every push)
1. Push this repo to GitHub.
2. Render dashboard → New → Web Service → connect the repo. Language: Docker. Instance type: Free. Auto-Deploy: On Commit.
3. Environment: `FH_SECRET` (random string), `FH_DB=/tmp/futurehuman.db`, optional `ANTHROPIC_API_KEY`. Health Check Path: `/healthz`.
Or use New → Blueprint, which reads `render.yaml`.
Free-plan limits: sleeps after 15 min idle (about 1 min to wake) and the filesystem is ephemeral, so accounts and memories reset on redeploy, restart or spin-down. For persistent data move to Postgres or a paid disk.

## Scope status
Working (v1.1 adds: hybrid vector search, learned alert scoring, rate limiting, morning brief, landing page): accounts, screen capture (browser, on-device OCR, text only), memory formation + linking + sessions, FTS5 hybrid search with graph expansion, evidence-linked answers, timeline filters, corrections/outdated/delete, live meeting commitments (WebSocket), summaries, briefs, email drafts, interruption scoring (blueprint formula), live alerts, floating AI (Ctrl/Cmd+K, double-Ctrl).
Not yet (see blueprint): Tauri desktop shell with OS-wide capture/system-audio loopback, Whisper/Deepgram diarisation, Neo4j + Qdrant (SQLite FTS5 + local hashed-vector index + link table stand in), Gmail/Calendar OAuth, local Llama scorer (a lightweight learned adjustment is used instead), rate limiting, Postgres.
