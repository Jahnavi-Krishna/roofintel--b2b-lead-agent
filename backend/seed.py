"""
seed.py

One-shot ingestion script: loads contractor records and pre-generates
sales insights for each. Stands in for the production pipeline.

Production version of this file (documented, not built today):
  - Replace the `json.load(open(...))` step with an async scraper hitting
    the GAF locator across a list of zip codes, on a schedule (e.g. nightly
    via a cron-triggered job or a queue worker), writing into the same
    `upsert_lead` call below.
  - Replace the synchronous for-loop insight generation with a task queue
    (Celery/RQ or a simple asyncio.gather with a concurrency limit) so
    generating insights for thousands of leads doesn't serialize on one
    process -- this script intentionally stays simple because the case
    study's data volume doesn't need it yet, not because the pattern
    doesn't generalize.

Run with: python seed.py
"""

import json
from pathlib import Path
import storage
import insight_generator

DATA_PATH = Path(__file__).parent / "data" / "contractors.json"


def run():
    storage.init_db()

    contractors = json.loads(DATA_PATH.read_text())
    print(f"Loaded {len(contractors)} contractor records from {DATA_PATH.name}")

    for c in contractors:
        storage.upsert_lead(c)
    print(f"Upserted {len(contractors)} leads into {storage.DB_PATH.name}")

    pending = storage.leads_missing_insights()
    print(f"Generating sales insights for {len(pending)} leads...")
    for i, lead in enumerate(pending, 1):
        insight = insight_generator.generate_insight(lead)
        storage.save_insight(lead["id"], insight)
        print(f"  [{i}/{len(pending)}] {lead['company_name']} -> tier {insight['priority_tier']} ({insight['priority_score']})")

    print("Done. Run `uvicorn main:app --reload` and open the frontend.")


if __name__ == "__main__":
    run()
