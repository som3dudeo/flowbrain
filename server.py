"""
server.py — FlowBrain FastAPI server with chat UI and automation API

Endpoints:
  GET  /           → Full chat web interface
  GET  /agents     → Registered agents and capabilities
  POST /route      → Route a request to the best agent
  POST /manage     → Agent-manager decision + execution/delegation plan
  POST /chat       → Main endpoint (OpenClaw + web UI use this)
  POST /search     → Raw semantic search (returns JSON)
  POST /preview    → Preview an automation (no side effects)
  POST /auto       → Find + optionally execute a workflow
  POST /execute    → Trigger a specific workflow via n8n webhook
  GET  /status     → Health check + index/agent stats
  GET  /docs       → Auto-generated API documentation

Run: python -m flowbrain start   (recommended)
     python server.py             (direct)
"""

import os
import uuid
import json
import time
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from collections import OrderedDict

# ── Load dotenv FIRST ────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from flowbrain import __version__
from flowbrain.agents import list_agents, route_request
from flowbrain.policies.risk import classify_risk, get_affected_systems
from flowbrain.policies.preview import build_preview
from flowbrain.policies.confidence import should_auto_execute as policy_should_auto_execute
from flowbrain.state.db import record_preview, new_preview_id, record_run
from router import get_router
from indexer import get_index_stats
from auto_executor import get_executor, AutoResult

# ── Config (dotenv already loaded) ───────────────────────────────────────────

PORT         = int(os.getenv("FLOWBRAIN_PORT", os.getenv("PORT", 8001)))
HOST         = os.getenv("FLOWBRAIN_HOST", os.getenv("HOST", "127.0.0.1"))
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")

# Safety thresholds
MIN_AUTOEXEC_CONFIDENCE = float(os.getenv("FLOWBRAIN_MIN_AUTOEXEC_CONFIDENCE", "0.85"))
MIN_PREVIEW_CONFIDENCE  = float(os.getenv("FLOWBRAIN_MIN_PREVIEW_CONFIDENCE", "0.40"))

logger = logging.getLogger(__name__)

# In-memory conversation history (keyed by session_id)
# Bounded to avoid unbounded growth under many unique session IDs.
_conversations: OrderedDict[str, list[dict]] = OrderedDict()
MAX_HISTORY = 20  # messages per session
MAX_SESSIONS = int(os.getenv("FLOWBRAIN_MAX_SESSIONS", "1000"))


def get_webhook_url(workflow_id: str) -> str | None:
    env_key = f"N8N_WEBHOOK_{workflow_id}"
    return os.getenv(env_key) or os.getenv("N8N_DEFAULT_WEBHOOK")


def _touch_session(session_id: str) -> list[dict]:
    history = _conversations.pop(session_id, [])
    _conversations[session_id] = history
    while len(_conversations) > MAX_SESSIONS:
        evicted_session_id, _ = _conversations.popitem(last=False)
        logger.warning("Evicted conversation history for session %s (max sessions=%s)", evicted_session_id, MAX_SESSIONS)
    return history


def _append_conversation(session_id: str, message: dict):
    history = _touch_session(session_id)
    history.append(message)
    if len(history) > MAX_HISTORY * 2:
        del history[:-MAX_HISTORY * 2]


# ── App setup ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n🚀 FlowBrain starting...")
    router = get_router()
    if router.is_ready:
        print(f"   ✅ {router.workflow_count:,} workflows indexed and ready")
    else:
        print("   ⚠️  No index found. Run `flowbrain reindex` first.")
    print(f"   🌐 http://{HOST}:{PORT}\n")
    yield


app = FastAPI(
    title="FlowBrain",
    description="AI-native automation operating system — semantic workflow search and execution",
    version=__version__,
    lifespan=lifespan,
)


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str
    session_id: str | None = None
    top_k:      int = 5

class SearchRequest(BaseModel):
    query:  str
    top_k:  int = 5

class ExecuteRequest(BaseModel):
    workflow_id: str
    query:       str
    params:      dict = {}
    session_id:  str | None = None

class AutoRequest(BaseModel):
    """
    Automation endpoint — provide a plain-English intent and the system
    finds the best workflow, extracts parameters, and optionally executes it.

    auto_execute defaults to False (preview-only). Set to True to actually
    fire the webhook, subject to confidence and risk gating.
    """
    intent: str
    params: dict = {}
    session_id: str | None = None
    auto_execute: bool = False


class RouteRequest(BaseModel):
    intent: str


class ManageRequest(BaseModel):
    intent: str
    auto_execute: bool = False
    session_id: str | None = None
    params: dict = {}


# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    router = get_router()
    n8n_ok = await _check_n8n()
    return {
        "status": "ready" if router.is_ready else "no_index",
        "workflows_indexed": router.workflow_count if router.is_ready else 0,
        "n8n_connected": n8n_ok,
        "n8n_url": N8N_BASE_URL,
        "active_sessions": len(_conversations),
        "registered_agents": len(list_agents()),
    }


@app.get("/agents")
async def agents():
    registry = list_agents()
    return {"count": len(registry), "agents": registry}


@app.post("/route")
async def route(req: RouteRequest):
    plan = route_request(req.intent)
    return {"intent": req.intent, **plan.__dict__}


@app.post("/manage")
async def manage(req: ManageRequest):
    plan = route_request(req.intent)
    response = {
        "intent": req.intent,
        "route": plan.__dict__,
        "manager_message": f"Selected {plan.selected_agent['name']} via {plan.execution_mode} mode.",
    }

    if plan.execution_mode == "workflow":
        auto_req = AutoRequest(
            intent=req.intent,
            params=req.params,
            session_id=req.session_id,
            auto_execute=req.auto_execute,
        )
        response["workflow_result"] = await auto(auto_req)
    else:
        response["delegation_ready"] = True
        response["next_step"] = plan.downstream_action

    return response


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Main chat endpoint. Used by the web UI, OpenClaw, and any other client.

    Returns:
      - reply: A human-readable text summary (for OpenClaw to display)
      - workflows: List of matching workflow objects
      - session_id: Use this in future requests to maintain conversation context
    """
    router = get_router()
    if not router.is_ready:
        return {
            "reply": "⚠️ The workflow index is not built yet. Run `flowbrain reindex` to get started.",
            "workflows": [],
            "session_id": req.session_id or str(uuid.uuid4()),
        }

    if not req.message.strip():
        return {"reply": "Please describe what you want to automate.", "workflows": [], "session_id": req.session_id}

    session_id = req.session_id or str(uuid.uuid4())
    message    = req.message.strip()

    # Store user message in history
    _append_conversation(session_id, {
        "role": "user", "content": message, "time": _now()
    })

    # Agent-manager routing first
    route_plan = route_request(message)

    # Semantic search
    results = router.search_dict(message, top_k=req.top_k)

    # Build human-readable reply
    if not results:
        reply = (
            f"I couldn't find a confident workflow match for \"{message}\". "
            f"Try using specific service names like 'Slack', 'Gmail', 'Airtable', etc."
        )
    elif len(results) == 1:
        r = results[0]
        reply = (
            f"I found **1 workflow** that matches your request ({r['confidence_pct']} confidence):\n\n"
            f"**{r['name']}**\n{r['description'] or ''}\n\n"
            f"Integrations: {', '.join(r['nodes'][:5]) or 'N/A'}\n"
            f"View: {r['source_url']}"
        )
    else:
        top = results[0]
        reply = (
            f"I found **{len(results)} workflows** matching your request. "
            f"Best match ({top['confidence_pct']}): **{top['name']}**"
        )

    # Store assistant response in history
    _append_conversation(session_id, {
        "role": "assistant",
        "content": reply,
        "workflows": results,
        "time": _now(),
    })

    return {
        "reply": reply,
        "workflows": results,
        "session_id": session_id,
        "count": len(results),
        "agent_route": route_plan.__dict__,
    }


@app.post("/search")
async def search(req: SearchRequest):
    """Raw semantic search — returns workflow matches as JSON."""
    router = get_router()
    if not router.is_ready:
        raise HTTPException(status_code=503, detail="Index not built. Run `flowbrain reindex`")
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    results = router.search_dict(req.query.strip(), top_k=req.top_k)
    return {"query": req.query, "count": len(results), "results": results}


@app.post("/execute")
async def execute(req: ExecuteRequest):
    """Trigger an n8n workflow via its configured webhook URL."""
    webhook_url = get_webhook_url(req.workflow_id)

    if not webhook_url:
        return JSONResponse(status_code=200, content={
            "success":     False,
            "demo_mode":   True,
            "workflow_id": req.workflow_id,
            "message": (
                f"No webhook configured for workflow '{req.workflow_id}'. "
                f"Add N8N_WEBHOOK_{req.workflow_id}=<webhook-url> to your .env file."
            ),
        })

    payload = {"workflow_id": req.workflow_id, "user_query": req.query, **req.params}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return {
                "success":     True,
                "workflow_id": req.workflow_id,
                "status_code": resp.status_code,
                "response":    resp.text[:2000],
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="n8n webhook timed out (30s)")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"n8n error: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PreviewRequest(BaseModel):
    """Preview an automation — no side effects."""
    intent: str
    session_id: str | None = None


@app.post("/preview")
async def preview(req: PreviewRequest):
    """
    Preview an automation without executing it.

    Shows: selected workflow, extracted params, confidence, risk level,
    affected systems, and whether auto-execution would be allowed.
    """
    router = get_router()
    if not router.is_ready:
        return {"error": "Index not built", "intent": req.intent}

    if not req.intent.strip():
        raise HTTPException(status_code=400, detail="Intent cannot be empty.")

    # Search for best workflow
    results = router.search(req.intent.strip(), top_k=3)

    if not results:
        return {
            "intent": req.intent,
            "workflow_name": None,
            "confidence": 0.0,
            "confidence_pct": "0%",
            "risk_level": "unknown",
            "message": "No matching workflow found.",
        }

    best = results[0]
    executor = get_executor()
    params = executor.extractor.extract(req.intent, best.nodes)

    # Risk classification / preview policy
    risk = classify_risk(best.nodes, best.name)
    systems = get_affected_systems(best.nodes)
    preview = build_preview(
        intent=req.intent,
        workflow_id=best.workflow_id,
        workflow_name=best.name,
        confidence=best.confidence,
        nodes=best.nodes,
        params=params,
        auto_execute_requested=False,
        alternatives=[
            {"name": r.name, "confidence": r.confidence, "confidence_pct": f"{int(r.confidence*100)}%"}
            for r in results[1:3]
        ],
        source_url=best.source_url,
    )
    would_auto = preview.would_auto_execute
    blocked = preview.execution_blocked
    block_reason = preview.block_reason

    alternatives = preview.alternatives

    # Record preview in state
    try:
        record_preview(
            preview_id=new_preview_id(),
            intent=req.intent,
            workflow_id=best.workflow_id,
            workflow_name=best.name,
            confidence=best.confidence,
            params=params,
            risk_level=risk.value,
            systems_affected=systems,
            blocked=blocked,
            block_reason=block_reason,
        )
    except Exception as e:
        logger.warning("Failed to record preview %s: %s", req.intent[:80], e)

    return {
        "intent": req.intent,
        "workflow_id": best.workflow_id,
        "workflow_name": best.name,
        "confidence": best.confidence,
        "confidence_pct": f"{int(best.confidence*100)}%",
        "risk_level": risk.value,
        "systems_affected": systems,
        "params_extracted": params,
        "would_auto_execute": would_auto,
        "execution_blocked": blocked,
        "block_reason": block_reason,
        "alternatives": alternatives,
        "source_url": best.source_url,
        "action_summary": f"Will interact with: {', '.join(systems)}" if systems else "Internal workflow",
    }


@app.post("/auto")
async def auto(req: AutoRequest):
    """
    ── The core automation endpoint ──

    Takes a plain-English intent, finds the best n8n workflow,
    extracts parameters, and optionally executes it.

    auto_execute=false (DEFAULT): search + extract + preview. No side effects.
    auto_execute=true: search + extract + confidence/risk check + execute.
    """
    t0 = time.time()
    router = get_router()
    if not router.is_ready:
        return {
            "success": False,
            "message": "Workflow index not built. Run `flowbrain reindex` first.",
            "intent": req.intent,
        }

    if not req.intent.strip():
        raise HTTPException(status_code=400, detail="Intent cannot be empty.")

    session_id = req.session_id or str(uuid.uuid4())
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    _append_conversation(session_id, {
        "role": "user", "content": req.intent, "time": _now(), "mode": "auto"
    })

    # ── Step 1: Search (no side effects) ──
    results = router.search(req.intent.strip(), top_k=3)
    if not results:
        msg = "No matching automation found. Try rephrasing or use more specific service names."
        _record_and_log(run_id, req, session_id, msg=msg, t0=t0)
        return {"success": False, "intent": req.intent, "message": msg,
                "session_id": session_id, "run_id": run_id, "auto_executed": False}

    best = results[0]
    wf_nodes = best.nodes  # real node metadata from ChromaDB

    # ── Step 2: Extract params (no side effects) ──
    executor = get_executor()
    params = executor.extractor.extract(req.intent, wf_nodes)
    params.update(req.params)  # user-provided params override

    # ── Step 3: Risk + confidence classification (no side effects) ──
    risk = classify_risk(wf_nodes, best.name)
    systems = get_affected_systems(wf_nodes)

    # ── Step 4: Gate decision ──
    execution_allowed = False
    block_reason = ""

    if not req.auto_execute:
        # User explicitly asked for preview only — never execute
        block_reason = "auto_execute=false (preview mode)"
    elif best.confidence < MIN_AUTOEXEC_CONFIDENCE:
        block_reason = (f"Confidence {int(best.confidence*100)}% is below "
                        f"auto-execution threshold ({int(MIN_AUTOEXEC_CONFIDENCE*100)}%)")
    elif not policy_should_auto_execute(best.confidence, risk.value, auto_execute_requested=True):
        block_reason = f"Blocked by safety policy (risk={risk.value}, confidence={int(best.confidence*100)}%)"
    else:
        execution_allowed = True

    # ── Step 5: Execute ONLY if allowed ──
    exec_result = {}
    actually_executed = False
    webhook_url = get_webhook_url(best.workflow_id)

    if execution_allowed:
        if not webhook_url:
            block_reason = "No webhook configured"
        else:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(webhook_url, json=params)
                    resp.raise_for_status()
                    exec_result = {"status_code": resp.status_code, "response": resp.text[:2000]}
                    actually_executed = True
            except httpx.TimeoutException:
                exec_result = {"error": "Webhook timed out (30s)"}
            except httpx.HTTPStatusError as e:
                exec_result = {"error": f"Webhook returned HTTP {e.response.status_code}"}
            except Exception as e:
                exec_result = {"error": str(e)}

    # ── Build response message ──
    success = actually_executed and "error" not in exec_result
    needs_webhook = not webhook_url

    if actually_executed and success:
        message = (
            f"✅ Executed: **{best.name}** ({int(best.confidence*100)}% confidence)\n"
            f"Risk: {risk.value} | Systems: {', '.join(systems) or 'none'}\n"
            f"Response: {exec_result.get('response', 'Done.')}"
        )
    elif actually_executed and not success:
        message = f"❌ Execution failed: {exec_result.get('error', 'Unknown error')}"
    elif needs_webhook:
        message = (
            f"Found: **{best.name}** ({int(best.confidence*100)}% confidence)\n"
            f"⚠️ No webhook configured. Add N8N_DEFAULT_WEBHOOK to .env."
        )
    elif block_reason:
        message = (
            f"Found: **{best.name}** ({int(best.confidence*100)}% confidence)\n"
            f"Risk: {risk.value} | Systems: {', '.join(systems) or 'none'}\n"
            f"⏸ Not executed: {block_reason}"
        )
    else:
        message = f"Found: **{best.name}** ({int(best.confidence*100)}% confidence)"

    duration_ms = int((time.time() - t0) * 1000)

    # Record in durable state
    try:
        record_run(
            run_id=run_id, intent=req.intent,
            workflow_id=best.workflow_id, workflow_name=best.name,
            confidence=best.confidence, params=params,
            auto_execute=req.auto_execute, success=success,
            execution_result=exec_result,
            error_message=block_reason if not success else "",
            needs_webhook=needs_webhook, source_url=best.source_url,
            duration_ms=duration_ms, risk_level=risk.value,
        )
    except Exception as e:
        logger.warning("Failed to record run %s: %s", run_id, e)

    _append_conversation(session_id, {
        "role": "assistant", "content": message,
        "workflow_name": best.name, "success": success, "time": _now(),
    })

    return {
        "success":          success,
        "run_id":           run_id,
        "intent":           req.intent,
        "workflow_id":      best.workflow_id,
        "workflow_name":    best.name,
        "confidence":       best.confidence,
        "confidence_pct":   f"{int(best.confidence * 100)}%",
        "risk_level":       risk.value,
        "systems_affected": systems,
        "params_extracted": params,
        "execution_result": exec_result,
        "message":          message,
        "needs_webhook":    needs_webhook,
        "source_url":       best.source_url,
        "session_id":       session_id,
        "auto_executed":    actually_executed,
        "block_reason":     block_reason,
        "duration_ms":      duration_ms,
    }


def _record_and_log(run_id, req, session_id, msg, t0):
    """Helper to record a failed/empty run."""
    duration_ms = int((time.time() - t0) * 1000)
    try:
        record_run(run_id=run_id, intent=req.intent, success=False,
                   error_message=msg, duration_ms=duration_ms, auto_execute=req.auto_execute)
    except Exception as e:
        logger.warning("Failed to record failed run %s: %s", run_id, e)
    _append_conversation(session_id, {
        "role": "assistant", "content": msg, "success": False, "time": _now(),
    })


@app.get("/history/{session_id}")
async def history(session_id: str):
    """Return conversation history for a session."""
    return {"session_id": session_id, "messages": _touch_session(session_id) if session_id in _conversations else []}


@app.delete("/history/{session_id}")
async def clear_history(session_id: str):
    """Clear conversation history for a session."""
    removed = _conversations.pop(session_id, None) is not None
    return {"cleared": removed}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_n8n() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{N8N_BASE_URL}/healthz")
            return r.status_code == 200
    except Exception as e:
        logger.debug("n8n health check failed: %s", e)
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Web UI ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(content=_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FlowBrain</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1117;--bg2:#161b27;--bg3:#1e2435;--bg4:#252b3d;
  --border:#2a3050;--border2:#363d5c;
  --accent:#f4821f;--accent2:#ff9a4a;--accent-dim:rgba(244,130,31,0.12);
  --text:#dde2f0;--muted:#6b7494;--muted2:#8891b0;
  --success:#3ecf8e;--error:#ff5c5c;--info:#5c9eff;
  --radius:14px;--radius-sm:8px;
}
html,body{height:100%;overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg);color:var(--text);display:flex;flex-direction:column}

/* ── Header ── */
.header{
  height:58px;background:var(--bg2);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;flex-shrink:0;z-index:10;
}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{
  width:32px;height:32px;border-radius:8px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0
}
.logo-text h1{font-size:15px;font-weight:700;letter-spacing:-.3px}
.logo-text p{font-size:11px;color:var(--muted);margin-top:1px}
.header-right{display:flex;align-items:center;gap:10px}
.badge{
  font-size:11px;padding:4px 10px;border-radius:20px;
  border:1px solid var(--border);color:var(--muted);
  display:flex;align-items:center;gap:5px;white-space:nowrap;
}
.badge.ok{border-color:rgba(62,207,142,.4);color:var(--success)}
.badge.warn{border-color:rgba(244,130,31,.4);color:var(--accent)}
.dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}

/* ── Layout ── */
.layout{display:flex;height:calc(100vh - 58px);overflow:hidden}

/* ── Sidebar ── */
.sidebar{
  width:220px;background:var(--bg2);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;
}
.sidebar-header{
  padding:14px 16px 10px;font-size:11px;font-weight:600;
  color:var(--muted);letter-spacing:.08em;text-transform:uppercase
}
.sidebar-list{flex:1;overflow-y:auto;padding:0 8px 8px}
.sidebar-item{
  padding:8px 10px;border-radius:var(--radius-sm);cursor:pointer;
  font-size:12px;color:var(--muted2);line-height:1.4;
  transition:all .15s;margin-bottom:2px;
}
.sidebar-item:hover{background:var(--bg3);color:var(--text)}
.sidebar-item.active{background:var(--accent-dim);color:var(--accent)}
.sidebar-empty{padding:16px;font-size:12px;color:var(--muted);text-align:center}
.sidebar-footer{padding:12px;border-top:1px solid var(--border)}
.btn-new{
  width:100%;padding:8px;border-radius:var(--radius-sm);border:1px solid var(--border);
  background:transparent;color:var(--muted2);font-size:12px;cursor:pointer;
  transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px
}
.btn-new:hover{border-color:var(--accent);color:var(--accent)}

/* ── Main chat area ── */
.chat-area{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.messages{flex:1;overflow-y:auto;padding:24px 20px;display:flex;flex-direction:column;gap:20px}
.messages::-webkit-scrollbar{width:4px}
.messages::-webkit-scrollbar-track{background:transparent}
.messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── Message bubbles ── */
.msg{display:flex;gap:10px;max-width:100%;animation:fadeUp .25s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg.user{flex-direction:row-reverse}
.avatar{
  width:30px;height:30px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:14px;margin-top:2px;
}
.msg.user .avatar{background:linear-gradient(135deg,#5c9eff,#8b5cf6)}
.msg.ai   .avatar{background:linear-gradient(135deg,var(--accent),var(--accent2))}
.bubble{
  max-width:72%;padding:12px 16px;border-radius:var(--radius);font-size:14px;
  line-height:1.65;
}
.msg.user .bubble{
  background:linear-gradient(135deg,#1e3a5f,#2a1f6e);
  border:1px solid rgba(92,158,255,.2);color:var(--text);
  border-bottom-right-radius:4px;
}
.msg.ai .bubble{
  background:var(--bg2);border:1px solid var(--border);color:var(--text);
  border-bottom-left-radius:4px;
}
.msg-time{font-size:10px;color:var(--muted);margin-top:4px;
  text-align:right}.msg.ai .msg-time{text-align:left}

/* ── Workflow result cards ── */
.results-wrap{margin-top:10px;display:flex;flex-direction:column;gap:8px;max-width:640px}
.wf-card{
  background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:14px;transition:border-color .2s;
}
.wf-card:hover{border-color:var(--border2)}
.wf-card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:6px}
.wf-name{font-size:13px;font-weight:600;line-height:1.4;flex:1}
.conf-pill{
  font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;
  white-space:nowrap;flex-shrink:0;
}
.conf-high  {background:rgba(62,207,142,.15);color:var(--success)}
.conf-med   {background:rgba(244,130,31,.15); color:var(--accent)}
.conf-low   {background:rgba(107,116,148,.15);color:var(--muted2)}
.wf-desc{font-size:12px;color:var(--muted2);line-height:1.55;margin-bottom:8px}
.wf-nodes{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}
.node-tag{
  font-size:10px;padding:2px 8px;border-radius:20px;
  background:var(--bg4);border:1px solid var(--border);color:var(--muted2);
}
.wf-actions{display:flex;gap:6px}
.btn-sm{
  font-size:11px;padding:5px 12px;border-radius:6px;cursor:pointer;
  transition:all .15s;display:inline-flex;align-items:center;gap:4px;
}
.btn-view{
  border:1px solid var(--border);background:transparent;color:var(--muted2);
  text-decoration:none;
}
.btn-view:hover{border-color:var(--border2);color:var(--text)}
.btn-exec{
  border:none;background:var(--accent);color:white;font-weight:600;
}
.btn-exec:hover{background:var(--accent2)}
.btn-exec:disabled{opacity:.5;cursor:not-allowed}
.exec-feedback{
  font-size:11px;padding:6px 10px;border-radius:6px;margin-top:6px;border:1px solid;
}
.exec-ok  {background:rgba(62,207,142,.1); border-color:var(--success);color:var(--success)}
.exec-demo{background:rgba(244,130,31,.1); border-color:var(--accent);color:var(--accent)}
.exec-err {background:rgba(255,92,92,.1);  border-color:var(--error);  color:var(--error)}

/* ── Welcome screen ── */
.welcome{
  flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;padding:40px 20px;text-align:center;
}
.welcome-icon{font-size:52px;margin-bottom:20px}
.welcome h2{font-size:22px;font-weight:700;margin-bottom:8px}
.welcome p{font-size:14px;color:var(--muted2);line-height:1.6;max-width:440px;margin-bottom:28px}
.examples-grid{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:520px}
.ex-chip{
  font-size:12px;padding:7px 14px;border-radius:20px;
  background:var(--bg3);border:1px solid var(--border);color:var(--muted2);
  cursor:pointer;transition:all .15s;
}
.ex-chip:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-dim)}

/* ── Input area ── */
.input-bar{
  padding:14px 20px;background:var(--bg2);border-top:1px solid var(--border);flex-shrink:0;
}
.input-row{
  display:flex;gap:8px;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:6px 6px 6px 16px;transition:border-color .2s;
}
.input-row:focus-within{border-color:var(--accent)}
#msg-input{
  flex:1;background:transparent;border:none;color:var(--text);font-size:14px;
  outline:none;resize:none;max-height:120px;min-height:22px;line-height:1.5;padding-top:2px;
}
#msg-input::placeholder{color:var(--muted)}
#send-btn{
  width:36px;height:36px;border-radius:8px;border:none;flex-shrink:0;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:white;cursor:pointer;font-size:16px;transition:opacity .15s,transform .1s;
  display:flex;align-items:center;justify-content:center;
}
#send-btn:hover{opacity:.9}
#send-btn:active{transform:scale(.95)}
#send-btn:disabled{opacity:.4;cursor:not-allowed}
.input-hint{font-size:11px;color:var(--muted);margin-top:7px;text-align:center}

/* ── Typing indicator ── */
.typing{display:flex;gap:4px;align-items:center;padding:10px 14px}
.typing-dot{width:7px;height:7px;border-radius:50%;background:var(--muted);
  animation:typing 1.2s infinite}
.typing-dot:nth-child(2){animation-delay:.2s}
.typing-dot:nth-child(3){animation-delay:.4s}
@keyframes typing{0%,60%,100%{transform:translateY(0);opacity:.4}
  30%{transform:translateY(-5px);opacity:1}}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <div class="logo-text">
      <h1>FlowBrain</h1>
      <p>AI-native automation operating system</p>
    </div>
  </div>
  <div class="header-right">
    <div class="badge" id="idx-badge"><div class="dot"></div> loading...</div>
    <div class="badge" id="n8n-badge"><div class="dot"></div> n8n</div>
  </div>
</div>

<!-- Layout -->
<div class="layout">

  <!-- Sidebar: conversation history -->
  <div class="sidebar">
    <div class="sidebar-header">Recent Searches</div>
    <div class="sidebar-list" id="sidebar-list">
      <div class="sidebar-empty">Your searches appear here</div>
    </div>
    <div class="sidebar-footer">
      <button class="btn-new" onclick="newSession()">＋ New Search</button>
    </div>
  </div>

  <!-- Main chat -->
  <div class="chat-area">
    <div class="messages" id="messages">
      <!-- Welcome screen shown on first load -->
      <div class="welcome" id="welcome">
        <div class="welcome-icon">🔍</div>
        <h2>What do you want to automate?</h2>
        <p>Describe what you want to do in plain English. FlowBrain will find the best n8n workflow, extract parameters, and execute it safely.</p>
        <div class="examples-grid">
          <div class="ex-chip" onclick="sendExample(this)">Notify Slack when Typeform submitted</div>
          <div class="ex-chip" onclick="sendExample(this)">Save Gmail attachments to Google Drive</div>
          <div class="ex-chip" onclick="sendExample(this)">Create Jira ticket from GitHub issue</div>
          <div class="ex-chip" onclick="sendExample(this)">Summarize emails with AI and post to Notion</div>
          <div class="ex-chip" onclick="sendExample(this)">Sync Airtable rows to HubSpot contacts</div>
          <div class="ex-chip" onclick="sendExample(this)">Send daily Slack digest from RSS feed</div>
          <div class="ex-chip" onclick="sendExample(this)">Post new YouTube videos to Discord</div>
          <div class="ex-chip" onclick="sendExample(this)">Backup Google Sheets to Dropbox weekly</div>
        </div>
      </div>
    </div>

    <!-- Input bar -->
    <div class="input-bar">
      <div class="input-row">
        <textarea id="msg-input" rows="1"
          placeholder="Describe what you want to automate..."
          oninput="autoResize(this)"
          onkeydown="handleKey(event)"></textarea>
        <button id="send-btn" onclick="sendMessage()" title="Send (Enter)">▶</button>
      </div>
      <div class="input-hint">Press Enter to search · Shift+Enter for new line</div>
    </div>
  </div>

</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let sessionId = null;
let searchHistory = [];   // [{query, time}]
let isLoading = false;

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  checkStatus();
  document.getElementById('msg-input').focus();
});

async function checkStatus() {
  try {
    const d = await (await fetch('/status')).json();
    const ib = document.getElementById('idx-badge');
    const nb = document.getElementById('n8n-badge');

    if (d.workflows_indexed > 0) {
      ib.innerHTML = `<div class="dot"></div> ${d.workflows_indexed.toLocaleString()} workflows`;
      ib.classList.add('ok');
      window._wfCount = d.workflows_indexed;
    } else {
      ib.innerHTML = `<div class="dot"></div> Index not built`;
      ib.classList.add('warn');
    }

    if (d.n8n_connected) {
      nb.innerHTML = `<div class="dot"></div> n8n connected`;
      nb.classList.add('ok');
    } else {
      nb.innerHTML = `<div class="dot"></div> n8n offline`;
      nb.classList.add('warn');
    }
  } catch(e) {
    document.getElementById('idx-badge').textContent = 'offline';
  }
}

// ── Sending messages ──────────────────────────────────────────────────────────
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function sendExample(el) {
  document.getElementById('msg-input').value = el.textContent;
  sendMessage();
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const msg   = input.value.trim();
  if (!msg || isLoading) return;

  // Hide welcome screen
  const welcome = document.getElementById('welcome');
  if (welcome) welcome.remove();

  input.value = '';
  autoResize(input);
  isLoading = true;
  document.getElementById('send-btn').disabled = true;

  appendMessage('user', msg);
  const typingId = appendTyping();

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: msg, session_id: sessionId, top_k: 5 }),
    });
    const data = await res.json();
    sessionId = data.session_id;

    removeTyping(typingId);
    appendAIResponse(data.reply, data.workflows || []);
    addToHistory(msg);
  } catch(err) {
    removeTyping(typingId);
    appendMessage('ai', '❌ Could not reach the server. Is it running?');
  } finally {
    isLoading = false;
    document.getElementById('send-btn').disabled = false;
    document.getElementById('msg-input').focus();
  }
}

// ── Message rendering ─────────────────────────────────────────────────────────
function appendMessage(role, text) {
  const msgs = document.getElementById('messages');
  const div  = document.createElement('div');
  div.className = `msg ${role}`;

  const avatar = role === 'user' ? '👤' : '⚡';
  const time   = new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});

  div.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div>
      <div class="bubble">${md(text)}</div>
      <div class="msg-time">${time}</div>
    </div>`;
  msgs.appendChild(div);
  scrollBottom();
  return div;
}

function appendAIResponse(reply, workflows) {
  const msgs = document.getElementById('messages');
  const div  = document.createElement('div');
  div.className = 'msg ai';

  const time = new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  const cards = workflows.map((wf, i) => renderCard(wf, i)).join('');

  div.innerHTML = `
    <div class="avatar">⚡</div>
    <div style="min-width:0;flex:1;max-width:680px">
      <div class="bubble">${md(reply)}</div>
      ${cards ? `<div class="results-wrap">${cards}</div>` : ''}
      <div class="msg-time">${time}</div>
    </div>`;
  msgs.appendChild(div);
  scrollBottom();
}

function renderCard(wf, idx) {
  const pct   = Math.round(wf.confidence * 100);
  const cls   = pct >= 65 ? 'conf-high' : pct >= 45 ? 'conf-med' : 'conf-low';
  const label = pct >= 65 ? '✓ Great match' : pct >= 45 ? '◎ Good match' : '~ Possible';

  const nodes = (wf.nodes || []).slice(0,6)
    .map(n => `<span class="node-tag">${esc(n)}</span>`).join('');

  const desc = wf.description
    ? `<div class="wf-desc">${esc(wf.description.slice(0,180))}${wf.description.length>180?'…':''}</div>`
    : '';

  const cardId = `card-${idx}-${Date.now()}`;

  return `
  <div class="wf-card" id="${cardId}">
    <div class="wf-card-top">
      <div class="wf-name">${esc(wf.name)}</div>
      <span class="conf-pill ${cls}">${label} · ${pct}%</span>
    </div>
    ${desc}
    ${nodes ? `<div class="wf-nodes">${nodes}</div>` : ''}
    <div class="wf-actions">
      <a class="btn-sm btn-view" href="${esc(wf.source_url)}" target="_blank" rel="noopener">
        ↗ n8n.io
      </a>
      <button class="btn-sm btn-exec" id="exec-${cardId}"
        onclick="execWorkflow('${esc(wf.workflow_id)}','${esc(wf.name)}','${cardId}')">
        ▶ Execute
      </button>
    </div>
    <div id="fb-${cardId}"></div>
  </div>`;
}

// ── Execute workflow ──────────────────────────────────────────────────────────
async function execWorkflow(workflowId, name, cardId) {
  const btn  = document.getElementById(`exec-${cardId}`);
  const fb   = document.getElementById(`fb-${cardId}`);
  const query = document.getElementById('msg-input').value || name;

  btn.disabled  = true;
  btn.innerHTML = '<span style="display:inline-block;width:10px;height:10px;border:2px solid rgba(255,255,255,.3);border-top-color:white;border-radius:50%;animation:spin .7s linear infinite;margin-right:4px"></span>Running...';

  try {
    const res  = await fetch('/execute', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({workflow_id: workflowId, query, session_id: sessionId}),
    });
    const data = await res.json();

    if (data.demo_mode) {
      fb.innerHTML = `<div class="exec-feedback exec-demo">
        ℹ️ Demo mode — add <code>N8N_WEBHOOK_${workflowId}=&lt;url&gt;</code> to .env to enable execution.
      </div>`;
    } else if (data.success) {
      fb.innerHTML = `<div class="exec-feedback exec-ok">✅ Workflow triggered! (HTTP ${data.status_code})</div>`;
    } else {
      fb.innerHTML = `<div class="exec-feedback exec-err">❌ ${esc(data.detail||'Failed')}</div>`;
    }
  } catch(e) {
    fb.innerHTML = `<div class="exec-feedback exec-err">❌ Server unreachable</div>`;
  } finally {
    btn.disabled  = false;
    btn.textContent = '▶ Execute';
  }
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function addToHistory(query) {
  searchHistory.unshift({query, time: new Date()});
  if (searchHistory.length > 20) searchHistory.pop();
  renderSidebar();
}

function renderSidebar() {
  const list = document.getElementById('sidebar-list');
  if (!searchHistory.length) {
    list.innerHTML = '<div class="sidebar-empty">Your searches appear here</div>';
    return;
  }
  list.innerHTML = searchHistory.map((h,i) =>
    `<div class="sidebar-item ${i===0?'active':''}" onclick="reuseQuery('${esc(h.query)}')">
      ${esc(h.query.slice(0,52))}${h.query.length>52?'…':''}
    </div>`
  ).join('');
}

function reuseQuery(q) {
  document.getElementById('msg-input').value = q;
  sendMessage();
}

function newSession() {
  sessionId = null;
  searchHistory = [];
  document.getElementById('messages').innerHTML = '';
  document.getElementById('sidebar-list').innerHTML =
    '<div class="sidebar-empty">Your searches appear here</div>';
  document.getElementById('msg-input').focus();
}

// ── Typing indicator ──────────────────────────────────────────────────────────
function appendTyping() {
  const msgs = document.getElementById('messages');
  const id   = 'typing-' + Date.now();
  const div  = document.createElement('div');
  div.className = 'msg ai';
  div.id = id;
  div.innerHTML = `
    <div class="avatar">⚡</div>
    <div class="bubble" style="padding:8px 14px">
      <div class="typing">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>`;
  msgs.appendChild(div);
  scrollBottom();
  return id;
}

function removeTyping(id) {
  document.getElementById(id)?.remove();
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function scrollBottom() {
  const m = document.getElementById('messages');
  requestAnimationFrame(() => m.scrollTop = m.scrollHeight);
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function esc(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// Minimal markdown: **bold**, `code`, newlines
function md(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/`(.+?)`/g,'<code style="background:var(--bg4);padding:1px 5px;border-radius:3px;font-size:12px">$1</code>')
    .replace(/\n/g,'<br>');
}
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # dotenv already loaded at top of file
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False, log_level="warning")
