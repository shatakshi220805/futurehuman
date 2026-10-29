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

## Scope status
Working: accounts, screen capture (browser, on-device OCR, text only), memory formation + linking + sessions, FTS5 hybrid search with graph expansion, evidence-linked answers, timeline filters, corrections/outdated/delete, live meeting commitments (WebSocket), summaries, briefs, email drafts, interruption scoring (blueprint formula), live alerts, floating AI (Ctrl/Cmd+K, double-Ctrl).
Not yet (see blueprint): Tauri desktop shell with OS-wide capture/system-audio loopback, Whisper/Deepgram diarisation, Neo4j + Qdrant (SQLite FTS5 + link table stand in), Gmail/Calendar OAuth, local Llama scorer, rate limiting, Postgres.
