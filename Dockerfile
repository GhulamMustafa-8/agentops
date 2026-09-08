# AgentOps — Dockerfile
# Per Constitution Phase 7: "Dockerize the whole system" for production-grade polish.
#
# Zero-cost by default (Principle #2): this image runs the FastAPI core only.
# It talks to Ollama running on the HOST machine (not inside this container),
# since bundling a full Ollama + model download into the image would bloat it
# significantly and isn't required to demo AgentOps itself.
#
# Build:  docker build -t agentops .
# Run:    docker run -p 8000:8000 -e OLLAMA_BASE_URL=http://host.docker.internal:11434 agentops
# (Prefer `docker compose up` — see docker-compose.yml — it wires this up for you.)

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (separate layer -> faster rebuilds when only
# application code changes, not requirements.txt).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the application code.
COPY . .

# SQLite database lives here — mount this as a volume (see docker-compose.yml)
# so agent run history survives container restarts/rebuilds.
RUN mkdir -p /app/data
ENV AGENTOPS_DB_PATH=/app/data/agentops.db

# Ollama backend location. Overridden by docker-compose.yml / -e flags.
# host.docker.internal resolves to the host machine from inside the container
# on Docker Desktop (Mac/Windows); on Linux add --add-host or use the compose file.
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENV LLM_MODEL=llama3.2

EXPOSE 8000

# No reload in production/container mode (reload is a dev-only uvicorn feature).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
