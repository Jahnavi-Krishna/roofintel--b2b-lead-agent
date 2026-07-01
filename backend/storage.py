"""
storage.py

Persistence layer for RoofIntel leads using SQLite.
Handles proper serialization of JSON arrays and precise status mutations.
"""

import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "roofintel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    zip             TEXT NOT NULL,
    distance_miles  REAL NOT NULL,
    rating          REAL NOT NULL,
    review_count    INTEGER NOT NULL,
    certifications  TEXT NOT NULL,   -- JSON array, stored as text
    phone           TEXT NOT NULL,
    logo_initial    TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    scraped_at      TEXT NOT NULL,
    priority_tier   TEXT,            -- 'A' | 'B' | 'C'
    priority_score  INTEGER,         -- 0-100
    why_now         TEXT,
    talking_points  TEXT,            -- JSON array, stored as text
    approach        TEXT,
    insight_generated_at TEXT,
    status          TEXT DEFAULT 'new',
    status_updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(priority_tier, priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_zip ON leads(zip);
"""

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["certifications"] = json.loads(d["certifications"]) if d["certifications"] else []
    d["talking_points"] = json.loads(d["talking_points"]) if d["talking_points"] else []
    d["has_insight"] = d["insight_generated_at"] is not None
    return d

def upsert_lead(lead: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO leads (
                id, company_name, city, state, zip, distance_miles,
                rating, review_count, certifications, phone, logo_initial,
                source_url, scraped_at
            ) VALUES (:id, :company_name, :city, :state, :zip, :distance_miles,
                      :rating, :review_count, :certifications, :phone,
                      :logo_initial, :source_url, :scraped_at)
            ON CONFLICT(id) DO UPDATE SET
                company_name=excluded.company_name,
                city=excluded.city,
                state=excluded.state,
                zip=excluded.zip,
                distance_miles=excluded.distance_miles,
                rating=excluded.rating,
                review_count=excluded.review_count,
                certifications=excluded.certifications,
                phone=excluded.phone,
                logo_initial=excluded.logo_initial,
                source_url=excluded.source_url,
                scraped_at=excluded.scraped_at
            """,
            {**lead, "certifications": json.dumps(lead["certifications"])},
        )

def save_insight(lead_id: str, insight: dict):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads SET
                priority_tier=:priority_tier,
                priority_score=:priority_score,
                why_now=:why_now,
                talking_points=:talking_points,
                approach=:approach,
                insight_generated_at=:insight_generated_at
            WHERE id=:id
            """,
            {
                "id": lead_id,
                "priority_tier": insight["priority_tier"],
                "priority_score": insight["priority_score"],
                "why_now": insight["why_now"],
                "talking_points": json.dumps(insight["talking_points"]),
                "approach": insight["approach"],
                "insight_generated_at": insight["generated_at"],
            },
        )

def get_lead(lead_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_dict(row) if row else None

def list_leads(
    zip_filter: str | None = None,
    state: str | None = None,
    min_rating: float | None = None,
    certification: str | None = None,
    tier: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM leads WHERE 1=1"
    params = []
    
    if zip_filter:
        query += " AND zip = ?"
        params.append(zip_filter)
    if state:
        query += " AND state = ?"
        params.append(state)
    if min_rating is not None:
        query += " AND rating >= ?"
        params.append(min_rating)
    if certification:
        query += " AND certifications LIKE ?"
        params.append(f"%{certification}%")
    if tier:
        query += " AND priority_tier = ?"
        params.append(tier)
        
    query += " ORDER BY priority_score IS NULL, priority_score DESC, rating DESC"
    
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]

def update_lead_status(lead_id: str, status: str) -> dict | None:
    valid_statuses = {"new", "contacted", "quote_requested", "not_interested"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")
        
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status = ?, status_updated_at = ? WHERE id = ?",
            (status, now_iso, lead_id),
        )
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_dict(row) if row else None

def leads_missing_insights() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE insight_generated_at IS NULL"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]