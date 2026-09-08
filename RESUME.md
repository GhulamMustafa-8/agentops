# AgentOps — Resume / Portfolio Bullets

## One-liner (for a projects list / GitHub description)

> Built a production-grade agent orchestration framework with containerized
> deployment, cost guardrails, and real-time observability — enabling safe
> multi-agent deployment at scale.

## Expanded bullets (for a resume "Projects" section)

- **Designed and built AgentOps**, a FastAPI-based orchestration framework
  for deploying, monitoring, and coordinating multiple AI agents — not a
  single-purpose bot, but the infrastructure layer underneath any number of
  agents.
- **Implemented full observability**: every agent run (success or failure)
  is persisted to SQLite with duration, status, and error detail, exposed
  via aggregate `/stats` and per-agent breakdowns.
- **Built cost/rate guardrails enforced before the LLM call**, not after —
  token-size caps, per-agent rate limiting (sliding window), and lifetime
  run caps, returning `HTTP 429` on breach to prevent runaway usage.
- **Engineered auto-recovery logic**: configurable retry policies plus
  automatic fallback-agent routing when a primary agent exhausts its
  retries, so failures degrade gracefully instead of crashing the pipeline.
- **Enabled agent-to-agent orchestration** via an in-memory message bus
  with auto-forwarding, letting one agent's output automatically trigger
  another agent's task — demonstrated with a live Researcher → Summarizer
  hand-off.
- **Shipped a live monitoring dashboard** (vanilla HTML/JS, zero build step)
  polling the API every few seconds to show agent status, run history, and
  success rates in real time.
- **Containerized the entire system with Docker/Compose** for one-command
  reproducible deployment, while keeping the whole stack zero-cost by
  running against a local Ollama LLM backend instead of a paid API.

## Talking points for interviews

- **Why a framework and not just an agent?** To demonstrate systems/infra
  thinking — the interesting engineering problems in production AI aren't
  "can the model answer this," they're "what happens when it can't":
  timeouts, retries, cost control, observability.
- **Why zero-cost?** Forces good architecture — you can't paper over a bad
  guardrail design by just paying for more tokens. It also makes the whole
  thing trivially demoable by anyone without needing API keys.
- **What would you add with more time?** Redis-backed message bus for
  multi-process/distributed agents, Postgres for the log store at scale,
  auth on the API, and per-agent cost tracking in real currency (not just
  token counts) once a paid backend is wired in.
