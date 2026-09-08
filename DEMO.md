# AgentOps — Demo Walkthrough Script

A ~4-5 minute script for recording a demo video of the project. Each section
maps to one feature/phase, so you can cut between them if you'd rather record
in pieces.

**Setup before recording:**
```bash
ollama serve                 # terminal 1
ollama pull llama3.2         # one-time, if not already pulled
docker compose up --build    # terminal 2 (or: uvicorn main:app --reload)
```
Have the dashboard (`http://localhost:8000/dashboard`) and a terminal with
`curl` + [`jq`](https://jqlang.org/) both visible on screen.

---

### 1. The pitch (15 seconds)

> "This is AgentOps — an orchestration framework for running and monitoring
> multiple AI agents safely. It's not one agent doing one task — it's the
> infrastructure layer underneath any number of agents: registering them,
> logging every run, enforcing cost/rate guardrails, and letting them talk
> to each other. Runs entirely on free, local tooling — zero paid API
> dependency."

### 2. Create agents (30 seconds)

```bash
curl -X POST localhost:8000/agents -d '{"name":"Researcher","role":"You research topics in depth."}'
curl -X POST localhost:8000/agents -d '{"name":"Summarizer","role":"You summarize text in one sentence."}'
```

> "Each agent is independent — its own role/system prompt, and optionally
> its own model or even its own backend server."

Point at the dashboard — the two new agents appear in the Agents table.

### 3. Run a task + show observability (45 seconds)

```bash
curl -X POST localhost:8000/agents/$RESEARCHER/run -d '{"task":"Explain how vaccines work"}'
```

> "Every single run — success or failure — gets logged to SQLite: the task,
> the result, how long it took, and the full error if something went wrong."

Point at the dashboard's "Recent Runs" table updating live, and hit `/stats`
to show the aggregate success rate / avg duration.

### 4. Guardrails in action (45 seconds)

```bash
curl -X PUT localhost:8000/guardrails -d '{"max_runs_per_minute": 1}'
curl -X POST localhost:8000/agents/$RESEARCHER/run -d '{"task":"one"}'   # 200 OK
curl -X POST localhost:8000/agents/$RESEARCHER/run -d '{"task":"two"}'  # 429!
```

> "Guardrails sit in front of the LLM call, not after it — so a runaway
> loop or a misbehaving client gets rejected before it ever costs anything.
> Token size, requests-per-minute, and a lifetime cap per agent are all
> configurable."

### 5. Multi-agent chaining (45 seconds)

```bash
curl -X POST localhost:8000/agents/$RESEARCHER/run \
  -d "{\"task\":\"Explain photosynthesis\",\"forward_to\":\"$SUMMARIZER\",\"auto_run_forward\":true}"
```

> "This is the multi-agent piece — the Researcher's result is automatically
> forwarded to the Summarizer's inbox, and the Summarizer immediately runs
> on it. One API call, two agents, a real hand-off."

Show both runs appearing in the dashboard / `/logs`.

### 6. Auto-recovery (30 seconds)

> "And if an agent fails — bad backend, timeout, whatever — AgentOps can
> retry automatically, and if it's still failing after N retries, route
> the task to a fallback agent instead of just erroring out."

```bash
curl -X POST localhost:8000/agents/$RESEARCHER/run \
  -d '{"task":"...", "max_retries": 2, "fallback_agent_id": "'$SUMMARIZER'"}'
```

Point out `retries_used` / `used_fallback` / `attempts` in the JSON response.

### 7. Close (15 seconds)

> "Everything you just saw — FastAPI, SQLite, the dashboard — runs in one
> Docker container, connecting out to a local Ollama instance. No API keys,
> no cloud bill, fully reproducible. Code's on GitHub, link below."

---

## Screenshot checklist (if doing stills instead of/alongside video)

- [ ] Dashboard with 2+ agents and several logged runs
- [ ] A `429` guardrail response in the terminal
- [ ] The auto-forward JSON response showing both `final_result` and `forward_run`
- [ ] `docker compose up` output showing a clean container start
- [ ] The architecture diagram from `README.md`
