"""
main.py

RoofIntel API -- B2B sales intelligence for roofing distributor reps.

Endpoints:
  GET  /health                 liveness check
  GET  /leads                  list leads, ranked by priority (rep's daily queue)
  GET  /leads/{id}              single lead detail
  POST /leads/{id}/regenerate-insight   re-run AI insight for one lead

Stateless by design: every request reads from SQLite directly, no
in-memory cache or session state. That means this can run behind a load
balancer with any number of replicas and zero session affinity -- the
same horizontal-scaling reasoning used in the Patsy/Aria stack, applied
here at the API layer instead of the chat-history layer.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

import storage
import insight_generator
import agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="RoofIntel API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened to the rep dashboard's real origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/leads")
def get_leads(
    zip: str | None = None,
    state: str | None = None,
    min_rating: float | None = None,
    certification: str | None = None,
    tier: str | None = None,
):
    """Returns leads, highest-priority first. Filter params here are the
    deterministic "basic" path -- a dropdown UI calls this directly with
    no AI involved. The InstaWorker agent's query_leads tool (agent.py)
    calls the same storage.list_leads() function underneath, so both
    paths stay consistent by construction."""
    return storage.list_leads(
        zip_filter=zip, state=state, min_rating=min_rating,
        certification=certification, tier=tier,
    )


@app.get("/leads/{lead_id}")
def get_lead(lead_id: str):
    lead = storage.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@app.post("/leads/{lead_id}/regenerate-insight")
def regenerate_insight(lead_id: str):
    """Manual re-run hook -- useful when underlying contractor data
    changes (re-scrape bumped the rating, new certification appeared) and
    a rep wants a fresh read without waiting for the next scheduled batch."""
    lead = storage.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    insight = insight_generator.generate_insight(lead)
    storage.save_insight(lead_id, insight)
    return storage.get_lead(lead_id)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@app.post("/agent/chat")
def agent_chat(req: ChatRequest):
    """The InstaWorker endpoint. Single-turn-in, multi-tool-call-out --
    the agent may call query_leads, explain_ranking, draft_outreach, or
    mark_lead_status any number of times (bounded by the circuit breaker
    in agent.py) before returning. tool_log is returned alongside the
    reply so the frontend can render an explicit, auditable trail of
    every action taken -- nothing happens silently."""
    history = [{"role": m.role, "content": m.content} for m in req.history]
    return agent.run_agent(req.message, history)