<h1 align="center">RoofIntel</h1>
<p align="center">A B2B lead intelligence agent for roofing distributors.</p>
<p align="center"><sub> By Jahnavi Kunapareddy</sub></p>

<p align="center">
  <img src="https://img.shields.io/badge/Agent-tool--calling-orange" alt="Tool-calling agent">
  <img src="https://img.shields.io/badge/GPT--4o-OpenAI-412991?logo=openai&logoColor=white" alt="GPT-4o">
  <img src="https://img.shields.io/badge/Scoring-deterministic-4CAF50" alt="Deterministic scoring">
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite-relational-003B57?logo=sqlite&logoColor=white" alt="SQLite">
</p>

---

Turns public GAF contractor directory data into a ranked, AI-annotated lead queue for distributor sales reps doing account planning — built as a case study for Instalily.

## The agent behind the ranking: it reads, explains, and acts

A chat panel (the "AI" button, bottom-right) is backed by a GPT-4o tool-calling loop that can **read** — query leads, explain why a lead is ranked where it is — and **take real action** — draft outreach copy, mark a lead's status, which actually writes to the database. Every tool call the agent makes is shown explicitly in the chat log, including writes, so a rep always knows exactly what the system just did.

## Who it's for

Distributor sales reps doing account planning who need to know not just *who* to call, but *why*, and *what to say*.

## What it actually does

- **Explainable, deterministic scoring** — `priority_score` / tier is a rule (certification tier + rating + review volume + proximity), not an LLM guess. A rep-facing ranking has to be reproducible, not just plausible.
- **GPT-4o account insights** — `why_now`, `talking_points`, and `approach` text, grounded only in scraped fields, explicitly instructed to never fabricate a decision-maker name.
- **Tiered views** — Tier A/B/C stacked by default; click a tier to isolate it, "All Tiers" brings the rest back.
- **Deterministic filters** — state / rating / certification dropdowns hit `GET /leads` directly with query params. No AI in the filter path — a fast, predictable path when a rep just wants to slice the list.
- **Dark/light theme**, persisted in `localStorage`; hover-border buttons animated via Motion rather than plain CSS transitions.

## Design decisions and trade-offs

- **SQLite, not because it's "the" production database** — it proves the schema and access patterns are relational and production-shaped. Swapping to Postgres is a connection-string change, not a rewrite.
- **Deterministic scoring over LLM scoring, on purpose** — explainability and reproducibility matter more than a marginally cleverer ranking for a rep deciding who to call today.
- **Live scraping was a deliberate scope cut.** The real GAF locator gates results behind a quiz and address validation. Reverse-engineering that live, under time pressure, would have traded away time from the insight and UI layers — where the actual product value is. The data here is 12 realistic sample records, schema-matched 1:1 to the live locator. Production path: a scheduled scraper across a zip-code list, writing through the same `upsert_lead()` call `seed.py` already uses.
- **Stateless API** — every read hits SQLite directly, no session store, no sticky-session overhead. Horizontally scalable with zero session affinity — the same reasoning behind the client-side chat history design in the Patsy/Aria stack.

## Known limitation

The agent's GPT-4o tool-calling path needs `OPENAI_API_KEY` set in the backend environment. As of this build, it's been verified against the graceful no-key fallback, but not yet exercised end-to-end against a live key — run one real query through `/agent/chat` before relying on it in a live demo.

## My role

Owned the full build solo: the deterministic scoring model, the GPT-4o insight generation (with its grounding constraints), the tool-calling agent and its four tools, the FastAPI backend, and the frontend — including the explicit UX call to log every agent action, write or read, in the visible chat trail.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | HTML/CSS/JS, Motion for animation |
| Backend | Python FastAPI |
| Storage | SQLite (relational, Postgres-portable) |
| LLM | OpenAI GPT-4o — insight generation + tool-calling agent loop |
| Agent tools | `query_leads`, `explain_ranking` (read-only) · `draft_outreach`, `mark_lead_status` (write) |

## Setup

**Backend**
```bash
cd backend
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # optional — falls back to a labeled heuristic if unset
python seed.py                  # loads sample data, generates insights
uvicorn main:app --reload       # http://localhost:8000
```

**Frontend** (second terminal)
```bash
cd frontend
python3 -m http.server 8080     # http://localhost:8080
```

Open [http://localhost:8080](http://localhost:8080).

## Roadmap

- Scheduled scraper across a zip-code list, replacing the curated sample dataset
- Firmographic API enrichment before the LLM call, so talking points can reference a real contact
- Postgres migration (connection-string change on top of the existing schema)

> Demo and screenshots coming soon.
