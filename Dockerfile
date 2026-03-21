# ─────────────────────────────────────────────────────────────────
# FlowBrain — Dockerfile
#
# Build:   docker build -t flowbrain .
# Run:     docker run -p 8001:8001 -v $(pwd)/data:/app/data flowbrain
# ─────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# System dependencies needed by sentence-transformers and chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY harvester.py indexer.py enricher.py router.py server.py run.py reranker.py embedding.py bootstrap.sh ./
COPY flowbrain/ flowbrain/
COPY .env.example .env.example

# Create data directories (will be overridden by volume mount)
RUN mkdir -p data/workflows data/chroma_db

# Port the server listens on
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8001/status || exit 1

# Default: start the server (assumes data is volume-mounted and already set up)
# Use `docker run ... python -m flowbrain install` for first-time setup
CMD ["python", "-m", "flowbrain", "start"]
