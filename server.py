"""
server.py — FastAPI server with full chat UI and OpenClaw API

Endpoints:
  GET  /           → Full chat web interface
  POST /chat       → Main endpoint (OpenClaw + web UI use this)
  POST /search     → Raw semantic search (returns JSON)
  POST /execute    → Trigger a workflow via n8n webhook
  GET  /status     → Health check + index stats
  GET  /docs       → Auto-generated API documentation

Run: python server.py
     python run.py         (recommended — handles setup automatically)
"""

import os
import uuid
import json
import httpx
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from router import get_router
from indexer import get_index_stats
from auto_executor import get_executor, AutoResult

# ── Config ────────────────────────────────────────────────────────────────────

PORT         = int(os.getenv("PORT", 8000))
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")

# In-memory conversation history (keyed by session_id)
# For production, swap with Redis or a database
_conversations: dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY = 20  # messages per session


def get_webhook_url(workflow_id: str) -> str | None:
    env_key = f"N8N_WEBHOOK_{workflow_id}"
    return os.getenv(env_key) or os.getenv("N8N_DEFAULT_WEBHOOK")


# ── App setup ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n🚀 n8n Flow Finder starting...")
    router = get_router()
    if router.is_ready:
        print(f"   ✅ {router.workflow_count:,} workflows indexed and ready")
    else:
        print("   ⚠️  No index found. Run `python run.py --setup` first.")
    print(f"   🌐 http://localhost:{PORT}\n")
    yield


app = FastAPI(
    title="n8n Flow Finder",
    description="Semantic workflow search and execution engine",
    version="2.0.0",
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
    Fully autonomous execution — provide the intent and the system
    finds, extracts parameters, and executes the best workflow automatically.
    This is the endpoint OpenClaw calls.
    """
    intent:     str
    params:     dict = {}           # optional override params
    session_id: str | None = None
    auto_execute: bool = True       # set False to preview without executing


# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    router = get_router()
    n8n_ok = await _check_n8n()
    return {
        "status":            "ready" if router.is_ready else "no_index",
        "workflows_indexed":  router.workflow_count if router.is_ready else 0,
        "n8n_connected":      n8n_ok,
        "n8n_url":            N8N_BASE_URL,
        "active_sessions":    len(_conversations),
    }


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
            "reply": "⚠️ The workflow index is not built yet. Run `python run.py --setup` to get started.",
            "workflows": [],
            "session_id": req.session_id or str(uuid.uuid4()),
        }

    if not req.message.strip():
        return {"reply": "Please describe what you want to automate.", "workflows": [], "session_id": req.session_id}

    session_id = req.session_id or str(uuid.uuid4())
    message    = req.message.strip()

    # Store user message in history
    _conversations[session_id].append({
        "role": "user", "content": message, "time": _now()
    })

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
    _conversations[session_id].append({
        "role": "assistant",
        "content": reply,
        "workflows": results,
        "time": _now(),
    })

    # Trim history
    if len(_conversations[session_id]) > MAX_HISTORY * 2:
        _conversations[session_id] = _conversations[session_id][-MAX_HISTORY * 2:]

    return {
        "reply":      reply,
        "workflows":  results,
        "session_id": session_id,
        "count":      len(results),
    }


@app.post("/search")
async def search(req: SearchRequest):
    """Raw semantic search — returns workflow matches as JSON."""
    router = get_router()
    if not router.is_ready:
        raise HTTPException(status_code=503, detail="Index not built. Run `python run.py --setup`")
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


@app.post("/auto")
async def auto(req: AutoRequest):
    """
    ── The core OpenClaw endpoint ──

    Fully autonomous: takes a plain-English intent, finds the best n8n workflow,
    extracts all required parameters, and executes it — no human involvement needed.

    This is what OpenClaw calls when the user says "do X for me".

    Example:
        POST /auto
        {"intent": "Send an email to alice@example.com saying the meeting is at 3pm tomorrow"}

    Returns:
        {
          "success": true,
          "workflow_name": "Send Email via Gmail",
          "confidence": 0.87,
          "params_extracted": {"to_email": "alice@example.com", "message": "..."},
          "message": "✅ Email sent successfully",
          "needs_webhook": false
        }
    """
    router = get_router()
    if not router.is_ready:
        return {
            "success": False,
            "message": "Workflow index not built. Run `python run.py --setup` first.",
            "intent": req.intent,
        }

    if not req.intent.strip():
        raise HTTPException(status_code=400, detail="Intent cannot be empty.")

    session_id = req.session_id or str(uuid.uuid4())

    # Log to conversation history
    _conversations[session_id].append({
        "role": "user", "content": req.intent, "time": _now(), "mode": "auto"
    })

    executor = get_executor()
    result: AutoResult = await executor.run(req.intent, req.params)

    # Log result to conversation history
    _conversations[session_id].append({
        "role": "assistant",
        "content": result.message,
        "workflow_name": result.workflow_name,
        "success": result.success,
        "time": _now(),
    })

    return {
        "success":          result.success,
        "intent":           result.intent,
        "workflow_id":      result.workflow_id,
        "workflow_name":    result.workflow_name,
        "confidence":       result.confidence,
        "confidence_pct":   f"{int(result.confidence * 100)}%",
        "params_extracted": result.params,
        "execution_result": result.execution_result,
        "message":          result.message,
        "needs_webhook":    result.needs_webhook,
        "source_url":       result.source_url,
        "session_id":       session_id,
    }


@app.get("/history/{session_id}")
async def history(session_id: str):
    """Return conversation history for a session."""
    return {"session_id": session_id, "messages": _conversations.get(session_id, [])}


@app.delete("/history/{session_id}")
async def clear_history(session_id: str):
    """Clear conversation history for a session."""
    _conversations.pop(session_id, None)
    return {"cleared": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_n8n() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{N8N_BASE_URL}/healthz")
            return r.status_code == 200
    except Exception:
        return False


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ── Web UI ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(content=_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>n8n Flow Finder</title>
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
      <h1>n8n Flow Finder</h1>
      <p>Semantic workflow search &amp; execution</p>
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
        <h2>Find your n8n workflow</h2>
        <p>Describe what you want to automate in plain English. I'll search through thousands of n8n workflows and find the best match for you.</p>
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
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False, log_level="warning")
