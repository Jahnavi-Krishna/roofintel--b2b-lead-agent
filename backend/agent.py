"""
agent.py

The InstaWorker layer. This is the part of the case study that actually
maps to what Instalily builds: an agent that takes an action inside a
system, not just a chatbot that answers questions about data.

Architecture is the same 5-iteration tool-calling loop used in the
Patsy/Aria stack: GPT-4o gets a system prompt, a set of tools, and a
hard iteration cap (circuit breaker). If it can't resolve to a clean
final answer within 5 tool-call rounds, it breaks gracefully instead of
looping forever or returning a blank response.

Two of the four tools are read-only (query_leads, explain_ranking).
Two actually mutate state (draft_outreach produces a new artifact,
mark_lead_status writes to the database). That split is deliberate --
see TOOLS below for the per-tool reasoning, and storage.update_lead_status
for why the write path is kept narrow and auditable.
"""

import os
import json
import httpx
from openai import OpenAI

import storage
import insight_generator

_client = None


def _get_client() -> OpenAI:
    """Lazy singleton.

    http_client=httpx.Client() below is deliberate, not decorative: recent
    openai-python versions (<=1.5x) construct their internal httpx client
    with a 'proxies' kwarg that newer httpx releases (0.28+) removed,
    raising a hard TypeError on init -- a known openai/httpx version-skew
    bug, independent of anything pinned in requirements.txt (pip's
    resolver, multiple pyenv shells, or a later `pip install` of an
    unrelated package can all silently bump httpx past 0.28). Passing our
    own plain httpx.Client() means the SDK uses it as-is instead of
    building one internally, so this is immune to that version skew
    regardless of what httpx version ends up installed."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            http_client=httpx.Client(),
        )
    return _client


MAX_ITERATIONS = 5  # circuit breaker -- bounds token cost and latency, same as Patsy/Aria

SYSTEM_PROMPT = """You are the RoofIntel InstaWorker -- an agent that helps a \
roofing materials distributor's sales rep work their lead queue. You are \
not a general chatbot: every response should either answer a direct \
question using real data (via query_leads / explain_ranking) or take a \
real action the rep asked for (via draft_outreach / mark_lead_status).

Rules:
- Never invent a lead, a fact, a phone number, or a person's name that \
isn't in the tool results. If you don't have it, say so.
- When you take a write action (mark_lead_status), always confirm exactly \
what you changed in plain language, so the rep can see what happened --
never act silently.
- Keep replies short and concrete. Reps are scanning between calls, not \
reading essays.
- If the rep asks about a company by its name (e.g., "Five Boro Roof Systems"), \
you MUST call query_leads first with NO parameters to retrieve the full list, \
scan the list to find the matching company_name, locate its exact "id", and \
THEN call explain_ranking or draft_outreach using that validated "id". Never guess an ID.
- If a request is ambiguous (e.g. "the top lead" with no prior context), \
call query_leads first to establish which lead that is before acting on it.
- CRITICAL: Never write mathematical equations using LaTeX code markup, backslashes, \
or block formatting like \\[ \\]. Explain the scoring criteria and rules using simple, \
plain, scannable conversational text.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_leads",
            "description": "Search and filter the current lead list. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Two-letter state code, e.g. 'NJ'"},
                    "min_rating": {"type": "number", "description": "Minimum star rating, 0-5"},
                    "certification": {"type": "string", "description": "Substring match, e.g. 'Master Elite'"},
                    "tier": {"type": "string", "enum": ["A", "B", "C"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_ranking",
            "description": "Returns the exact scoring breakdown for one lead -- why it's ranked where it is. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_outreach",
            "description": "Generates a short call script or email draft for one lead, grounded in its real data. This is an action, not a question -- it produces a usable artifact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "channel": {"type": "string", "enum": ["call", "email"]},
                },
                "required": ["lead_id", "channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_lead_status",
            "description": "Writes a status onto a lead -- the one tool that mutates real data. Use only when the rep explicitly asks to log an action they took.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["new", "contacted", "quote_requested", "not_interested"]},
                },
                "required": ["lead_id", "status"],
            },
        },
    },
]


def _tool_query_leads(args: dict) -> dict:
    leads = storage.list_leads(
        state=args.get("state"),
        min_rating=args.get("min_rating"),
        certification=args.get("certification"),
        tier=args.get("tier"),
    )
    # Trim payload for the model -- it doesn't need full insight text to
    # answer "how many NJ leads do we have," just the identifying fields.
    return {
        "count": len(leads),
        "leads": [
            {
                "id": l["id"], "company_name": l["company_name"], "city": l["city"],
                "state": l["state"], "rating": l["rating"], "priority_tier": l["priority_tier"],
                "priority_score": l["priority_score"], "status": l["status"],
            }
            for l in leads
        ],
    }


def _tool_explain_ranking(args: dict) -> dict:
    lead = storage.get_lead(args["lead_id"])
    if not lead:
        return {"error": f"No lead with id {args['lead_id']}"}
    breakdown = insight_generator.compute_priority(lead)
    return {
        "company_name": lead["company_name"],
        "priority_score": breakdown["priority_score"],
        "priority_tier": breakdown["priority_tier"],
        "scoring_factors": {
            "certifications": lead["certifications"],
            "rating": lead["rating"],
            "review_count": lead["review_count"],
            "distance_miles": lead["distance_miles"],
        },
        "scoring_rule": "Score is calculated out of 100 max: Top Certification Weight + Rating Score (up to 30) + Review Count Score (up to 20) + Proximity Score (up to 15).",
    }


def _tool_draft_outreach(args: dict) -> dict:
    lead = storage.get_lead(args["lead_id"])
    if not lead:
        return {"error": f"No lead with id {args['lead_id']}"}
    channel = args.get("channel", "call")
    # Deterministic template grounded in real lead fields -- no separate
    # LLM call needed here; the outer agent call is already the LLM turn
    # that decided to invoke this tool, so it can write the draft itself
    # in its final response using this structured context.
    return {
        "company_name": lead["company_name"],
        "channel": channel,
        "context_for_draft": {
            "certifications": lead["certifications"],
            "rating": lead["rating"],
            "why_now": lead.get("why_now"),
            "approach": lead.get("approach"),
            "phone": lead["phone"],
        },
        "instruction": f"Write a brief, concrete {channel} {'script' if channel == 'call' else 'email draft'} for this contractor using the context above. Reference their certification tier and rating naturally. Do not invent a contact name.",
    }


def _tool_mark_lead_status(args: dict) -> dict:
    try:
        updated = storage.update_lead_status(args["lead_id"], args["status"])
    except ValueError as e:
        return {"error": str(e)}
    if not updated:
        return {"error": f"No lead with id {args['lead_id']}"}
    return {
        "confirmed": True,
        "company_name": updated["company_name"],
        "new_status": updated["status"],
    }


TOOL_MAP = {
    "query_leads": _tool_query_leads,
    "explain_ranking": _tool_explain_ranking,
    "draft_outreach": _tool_draft_outreach,
    "mark_lead_status": _tool_mark_lead_status,
}


def run_agent(message: str, history: list[dict] | None = None) -> dict:
    """Runs one agent turn. Returns the final text reply plus a log of
    every tool call made, so the frontend can render an explicit
    confirmation trail -- nothing the agent does should be invisible,
    especially the write action."""
    if not os.environ.get("OPENAI_API_KEY"):
        return {
            "reply": "InstaWorker needs an OPENAI_API_KEY set in the backend environment to run. Set it and restart uvicorn.",
            "tool_log": [],
        }

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": message})

    tool_log = []
    client = _get_client()

    for _ in range(MAX_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=TOOLS,
                temperature=0.3,
            )
        except Exception as e:
            # Any API-layer failure (bad/expired key, rate limit, network
            # issue, model error) surfaces here as a readable message
            # instead of an unhandled 500 -- same "never a blank screen"
            # principle as the insight_generator fallback, applied to the
            # interactive path where a silent crash is worse, because a
            # rep is watching it happen live.
            return {
                "reply": f"InstaWorker hit an API error and couldn't complete that request: {e}",
                "tool_log": tool_log,
            }

        msg = response.choices[0].message

        if not msg.tool_calls:
            return {"reply": msg.content, "tool_log": tool_log}

        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            fn_name = call.function.name
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args = {}
            handler = TOOL_MAP.get(fn_name)
            result = handler(args) if handler else {"error": f"Unknown tool {fn_name}"}

            tool_log.append({"tool": fn_name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    # Circuit breaker tripped -- graceful fallback, never a blank screen.
    return {
        "reply": "I wasn't able to finish that within my step limit. Here's what I found so far -- try breaking the request into smaller steps.",
        "tool_log": tool_log,
    }