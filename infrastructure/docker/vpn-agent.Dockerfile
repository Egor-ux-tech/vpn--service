# Build context: ./vpn
# NOTE: this image is meant to run directly on a VPN exit server (or in a privileged
# container with NET_ADMIN) alongside a real `wireguard-tools` installation and an already
#-configured wg0 interface (see infrastructure/ansible/roles/wireguard). It is intentionally
# NOT part of docker-compose.yml's local dev stack.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

VOLUME ["/var/lib/vpn-agent"]

EXPOSE 8800

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD curl -f http://localhost:8800/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8800"]
