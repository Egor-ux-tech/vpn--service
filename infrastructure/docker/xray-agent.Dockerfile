# Build context: ./xray-agent
# NOTE: this image is meant to run alongside a real Xray-core process (installed
# natively — see infrastructure/ansible/roles/xray — not bundled in this image) with its
# HandlerService gRPC API bound to 127.0.0.1. It is intentionally NOT part of
# docker-compose.yml's local dev stack, same as vpn-agent.Dockerfile.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

VOLUME ["/var/lib/xray-agent"]

EXPOSE 8801

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD curl -f http://localhost:8801/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8801"]
