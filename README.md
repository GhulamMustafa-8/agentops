# AgentOps

**A production-grade orchestration framework for deploying, monitoring, and managing multiple AI agents safely.**

AgentOps is not "one more AI agent that does one task." It's the **infrastructure layer** underneath any number of agents — registering them, running them, watching them, protecting against cost overruns and failures, and letting them talk to each other.

Built entirely on **free/local tooling** (FastAPI, SQLite, Ollama) — zero paid API dependency required to run or demo.

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
  - [Option A: Docker (recommended)](#option-a-docker-recommended)
  - [Option B: Local Python](#option-b-local-python)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Demo Walkthrough](#demo-walkthrough)
- [Project Structure](#project-structure)
- [Design Principles](#design-principles)
- [Roadmap](#roadmap)

---

## Architecture

```
                ┌─────────────────────┐
                │  Dashboard (HTML/JS) │  GET /dashboard
                └──────────┬──────────┘
                           │ polls every 4s
                ┌──────────▼──────────┐
                │     FastAPI Core     │
                │      (main.py)       │
                └──────────┬──────────┘
         ┌─────────────────┼──────────────────┬───────────────┐
         │                 │                  │               │
 ┌───────▼──────┐  ┌───────▼──────┐  ┌────────▼───────┐ ┌─────▼──────┐
 │ Agent Registry│  │ Agent Logger │  │  Guardrails    │ │ Message Bus│
 │ (in-memory)   │  │  (SQLite)    │  │ (rate/token/   │ │ (in-memory)│
 │               │  │              │  │  lifetime caps)│ │            │
 └───────┬──────┘  └──────────────┘  └────────────────┘ └────────────┘
         │
 ┌───────▼──────────────────────────────┐
 │  Recovery Layer (retry + fallback)    │
 └───────┬──────────────────────────────┘
         │
 ┌───────▼──────────────────────────────┐
 │      Agents (N) — BaseAgent           │
 │  each wraps an LLMClient -> Ollama    │
 │  (per-agent model / base_url support) │
 └────────────────────────────────────────┘
```

Every request to run a task flows through the same pipeline, in this order:

1. **Guardrails** check the request (token size, rate limit, lifetime cap) — rejected requests (`HTTP 429`) never reach the LLM.
2. **Recovery layer** executes the task, retrying on failure and optionally routing to a fallback agent.
3. **Logger** persists every individual attempt (not just the final result) to SQLite.
4. **Message Bus** optionally forwards the result to another agent, chaining multi-agent workflows.
5. **Dashboard** polls the above and renders it live.

---

## Quick Start

**Two LLM backend options** — pick whichever suits you:

| | Ollama (local) | Groq (hosted, free tier) |
|---|---|---|
| Setup | Install Ollama + download a model (a few GB) | Sign up at [console.groq.com](https://console.groq.com), get a free API key |
| Speed to first run | Slower (download-dependent) | Instant, no download |
| Internet needed at runtime | No | Yes |
| Cost | Free | Free tier |

### Option A: Docker (recommended)

**Prerequisites:** Docker, and [Ollama](https://ollama.com) running natively on your host machine.

```bash
# 1. Make sure Ollama is running and has a model pulled
ollama serve                # in one terminal
ollama pull llama3.2        # in another (one-time)

# 2. Build and start AgentOps
docker compose up --build

# 3. Open the dashboard
open http://localhost:8000/dashboard
```

The container talks to Ollama on your host via `host.docker.internal:11434` — no Ollama installation inside the container needed. See the comments in `docker-compose.yml` if you'd rather run Ollama in its own container instead.

### Option B: Local Python (Ollama)

**Prerequisites:** Python 3.10+, and Ollama running locally.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start Ollama in another terminal
ollama serve
ollama pull llama3.2

# 3. Run AgentOps
uvicorn main:app --reload --port 8000

# 4. Open the dashboard
open http://localhost:8000/dashboard
```

### Option C: Local Python (Groq — no download needed)

**Prerequisites:** Python 3.10+, and a free API key from [console.groq.com/keys](https://console.groq.com/keys).

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your free Groq API key and switch the default backend
#    (Windows PowerShell: use $env:LLM_BACKEND="groq" instead of export)
export LLM_BACKEND=groq
export GROQ_API_KEY=your_key_here
export LLM_MODEL=llama-3.1-8b-instant

# 3. Run AgentOps
uvicorn main:app --reload --port 8000

# 4. Open the dashboard
open http://localhost:8000/dashboard
```

With this, every new agent defaults to Groq — no local model download at all. You can still mix and match: any individual agent can override its own `backend`/`model`/`base_url` at creation time (`POST /agents`), regardless of the server-wide default.

---

## Configuration

All configuration is via environment variables — nothing is hardcoded.

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | `ollama` | Default LLM backend for new agents: `ollama` or `groq`. |
| `LLM_MODEL` | `llama3.2` (ollama) / `llama-3.1-8b-instant` (groq) | Default model name for new agents (overridable per-agent). |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Default Ollama server URL (overridable per-agent). |
| `GROQ_API_KEY` | *(none)* | Required if using the Groq backend. Free key at [console.groq.com/keys](https://console.groq.com/keys). |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq endpoint (rarely needs changing). |
| `AGENTOPS_DB_PATH` | `agentops.db` | SQLite file path for run logs. |

Per-agent overrides (`model`, `base_url`, `backend`) are set at creation time via `POST /agents` — this lets different agents use different models, backends, or even different servers entirely, which is what makes the **fallback agent** feature (Phase 6) meaningfully testable (e.g. an Ollama agent falling back to a Groq agent).

---

## API Reference

### Agents

| Method | Path | Description |
|---|---|---|
| `POST` | `/agents` | Create an agent. Body: `{name, role, model?, base_url?}` |
| `GET` | `/agents` | List all agents |
| `GET` | `/agents/{id}` | Get one agent |
| `DELETE` | `/agents/{id}` | Delete an agent |
| `POST` | `/agents/{id}/run` | Run a task (see below for all options) |

**`POST /agents/{id}/run` body:**

```jsonc
{
  "task": "Summarize the water cycle",
  "max_retries": 2,                 // optional, 0-5, default 0 (Phase 6)
  "fallback_agent_id": "uuid",      // optional (Phase 6)
  "forward_to": "uuid",             // optional (Phase 5)
  "auto_run_forward": true          // optional, requires forward_to (Phase 5)
}
```

The response always includes `status`, `result`/`error`, `duration_ms`, `run_id`, `approx_input_tokens`, `retries_used`, `used_fallback`, and the full `attempts` history.

### Observability (Phase 2)

| Method | Path | Description |
|---|---|---|
| `GET` | `/logs` | Run history. Query: `agent_id?`, `limit?`, `offset?` |
| `GET` | `/stats` | Aggregate stats (success rate, avg duration, per-agent breakdown) |

### Guardrails (Phase 3)

| Method | Path | Description |
|---|---|---|
| `GET` | `/guardrails` | Current guardrail config |
| `PUT` | `/guardrails` | Update config: `{max_tokens_per_task, max_runs_per_agent, max_runs_per_minute}` |
| `GET` | `/guardrails/{agent_id}/usage` | An agent's current usage against the caps |

### Messaging (Phase 5)

| Method | Path | Description |
|---|---|---|
| `POST` | `/messages/send` | Send a message: `{from_agent_id, to_agent_id, content}` |
| `GET` | `/messages/inbox/{agent_id}` | Read an agent's inbox. Query: `unread_only?` |
| `POST` | `/messages/inbox/{agent_id}/read` | Mark message(s) read. Query: `message_id?` (omit = mark all) |

### Dashboard (Phase 4)

| Method | Path | Description |
|---|---|---|
| `GET` | `/dashboard` | The live HTML dashboard |
| `GET` | `/dashboard/summary` | JSON data the dashboard polls |

---

## Demo Walkthrough

A scripted end-to-end demo you can run with `curl` (or paste into the interactive docs at `http://localhost:8000/docs`):

```bash
# 1. Create two agents
RESEARCHER=$(curl -s -X POST localhost:8000/agents \
  -d '{"name":"Researcher","role":"You research topics in depth."}' | jq -r .id)
SUMMARIZER=$(curl -s -X POST localhost:8000/agents \
  -d '{"name":"Summarizer","role":"You summarize text in one sentence."}' | jq -r .id)

# 2. Run a task on the Researcher, auto-forward the result to the Summarizer,
#    and have the Summarizer immediately run on it too (Phase 5 chaining)
curl -s -X POST localhost:8000/agents/$RESEARCHER/run \
  -d "{\"task\":\"Explain how vaccines work\",\"forward_to\":\"$SUMMARIZER\",\"auto_run_forward\":true}"

# 3. Watch it live
open http://localhost:8000/dashboard

# 4. Check guardrails in action — set a tight rate limit, then exceed it
#    (use a FRESH agent here — one that hasn't run yet, so the limit
#    starts from zero rather than counting runs from earlier in this demo)
GUARD_TEST=$(curl -s -X POST localhost:8000/agents \
  -d '{"name":"GuardrailDemo","role":"test"}' | jq -r .id)
curl -s -X PUT localhost:8000/guardrails -d '{"max_runs_per_minute": 1}'
curl -s -X POST localhost:8000/agents/$GUARD_TEST/run -d '{"task":"one"}'   # -> HTTP 200
curl -s -X POST localhost:8000/agents/$GUARD_TEST/run -d '{"task":"two"}'  # -> HTTP 429

# 5. Full run history + aggregate stats
curl -s localhost:8000/logs | jq
curl -s localhost:8000/stats | jq
```

---

## Project Structure

```
agentops/
├── main.py                  # FastAPI app & all routes
├── core/
│   ├── registry.py          # Agent registry (create/list/get/delete)
│   ├── logger.py            # SQLite run logging + stats aggregation
│   ├── llm_client.py        # Ollama API wrapper
│   ├── guardrails.py        # Token cap / rate limit / lifetime cap enforcement
│   ├── message_bus.py       # In-memory agent-to-agent messaging
│   └── recovery.py          # Retry + fallback-agent orchestration
├── agents/
│   └── base_agent.py        # BaseAgent — the atomic unit AgentOps runs
├── dashboard/
│   └── index.html           # Single-file live dashboard (polls the API)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Design Principles

1. **Framework over feature** — AgentOps manages agents; it isn't itself just one agent.
2. **Zero-cost by default** — runs entirely on free/local tooling (Ollama + SQLite). No paid API required.
3. **Observable by design** — every single run attempt is logged: task, result, duration, status, errors.
4. **Fail-safe** — `BaseAgent.run()` never raises; agent errors are caught and tracked, never left to crash the system.
5. **Incremental delivery** — built phase by phase, with a working system at the end of every phase.

---

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Core skeleton (FastAPI + Ollama client + BaseAgent + Registry) | ✅ Done |
| 2 | Observability (SQLite logging, `/logs`, `/stats`) | ✅ Done |
| 3 | Guardrails (token cap, rate limit, lifetime cap → HTTP 429) | ✅ Done |
| 4 | Dashboard (live HTML/JS UI) | ✅ Done |
| 5 | Multi-agent communication (`/messages/*`, auto-forward) | ✅ Done |
| 6 | Auto-recovery (retries + fallback agent routing) | ✅ Done |
| 7 | Packaging (Docker + this README) | ✅ Done |
| 8 | Final polish + demo recording + resume bullets | ⏳ Next |

---

**Resume pitch:** *Built a production-grade agent orchestration framework with containerized deployment, cost guardrails, and real-time observability — enabling safe multi-agent deployment at scale.*
