# RoofIntel — B2B Sales Intelligence for Roofing Distributors

Case study build for Instalily. Turns public GAF contractor directory data
into a ranked, AI-annotated lead queue for distributor sales reps doing
account planning.

## Run it

```bash
cd backend
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # optional — falls back to a labeled heuristic if unset
python seed.py                  # loads sample data, generates insights
uvicorn main:app --reload       # http://localhost:8000
```

In a second terminal:

```bash
cd frontend
python3 -m http.server 8080     # http://localhost:8080
```

Open `http://localhost:8080`.

## What's new since the first pass

- **Dark/light theme** — toggle in the header, persisted in localStorage.
- **Hover-border buttons** — animated via Motion (motion.dev), not CSS transitions.
- **Tier sections** — Tier A/B/C stacked vertically by default; click a tier
  button to isolate just that section, click "All Tiers" to bring the rest back.
- **Deterministic filters** — state / rating / certification dropdowns, no AI,
  hits `GET /leads` with query params directly.
- **InstaWorker agent** — the actual differentiator. A chat panel (bottom-right
  "AI" button) backed by `POST /agent/chat`, running a GPT-4o tool-calling
  loop with 4 tools: `query_leads` and `explain_ranking` (read-only),
  `draft_outreach` and `mark_lead_status` (take real action — the second one
  writes to the database). Every tool call the agent makes is shown explicitly
  in the chat log, including writes, so nothing happens silently.

**Known limitation to test before you're live**: the agent's GPT-4o tool-calling
path needs `OPENAI_API_KEY` set in the backend environment and hasn't been
exercised against a real key in this build session — only the graceful
no-key fallback was verified. Run one real query against `/agent/chat` before
relying on it in the room.


- **Data**: 12 realistic sample contractor records, schema matched 1:1 to
  the live GAF locator (`/roofing-contractors/residential`), reverse-engineered
  live on-site via DevTools. The live locator gates results behind a quiz
  flow and validated-address requirement — scraping it live was a scope
  cut I made deliberately to protect build time on the insight + UI layers,
  which is where the actual product value is. Production path: a scheduled
  scraper hitting the locator across a zip-code list, written into the same
  `upsert_lead()` call `seed.py` already uses.
- **Storage**: SQLite, not because it's "the" production database, but to
  prove the schema and access patterns are relational and production-shaped.
  Swapping to Postgres is a connection-string change, not a rewrite.
- **Scoring**: priority_score/tier is a deterministic rule (certification
  tier + rating + review volume + proximity), not LLM output — a
  rep-facing ranking needs to be explainable and reproducible.
- **Insight text** (why_now / talking_points / approach): GPT-4o, grounded
  only in the scraped fields, explicit instruction never to fabricate a
  decision-maker name. Production extension: enrich with a firmographic API
  before the LLM call so talking points can reference a real contact.
- **Stateless API**: every read hits SQLite directly, no session state —
  horizontally scalable with zero session affinity, same reasoning as the
  Patsy/Aria stack's client-side history design.