.PHONY: help up down logs backend-shell bot-shell migrate makemigrations \
        lint fmt typecheck test test-backend test-bot test-vpn e2e-smoke \
        backend-dev bot-dev frontend-dev seed expiry-worker create-admin \
        up-prod down-prod logs-prod

COMPOSE := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

help:
	@echo "make up               - start backend, bot, postgres, redis"
	@echo "make up-monitoring    - also start prometheus + grafana"
	@echo "make down             - stop and remove containers"
	@echo "make logs             - tail logs for all services"
	@echo "make migrate          - apply alembic migrations"
	@echo "make makemigrations m='msg' - generate a new alembic revision"
	@echo "make lint             - ruff check backend/ bot/ vpn/ xray-agent/"
	@echo "make fmt              - ruff format backend/ bot/ vpn/ xray-agent/"
	@echo "make typecheck        - mypy backend/ bot/ vpn/ xray-agent/"
	@echo "make test             - run all python test suites"
	@echo "make e2e-smoke        - cross-service E2E test: real backend + vpn-agent processes (see tests/README.md)"
	@echo "make backend-dev      - run backend locally with uvicorn --reload"
	@echo "make bot-dev          - run bot locally"
	@echo "make frontend-dev     - run admin panel locally"
	@echo "make expiry-worker    - run the subscription-expiry sweep once (cron/systemd timer in prod)"
	@echo "make create-admin     - create an admin panel account (make create-admin email=you@example.com)"
	@echo "make up-prod          - start the production stack (Caddy TLS + backend + bot + frontend) — see docs/deployment.md"
	@echo "make down-prod        - stop the production stack"
	@echo "make logs-prod        - tail logs for the production stack"

up:
	$(COMPOSE) up -d --build backend bot postgres redis

up-monitoring:
	$(COMPOSE) --profile monitoring up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

backend-shell:
	$(COMPOSE) exec backend bash

bot-shell:
	$(COMPOSE) exec bot bash

migrate:
	$(COMPOSE) exec backend alembic upgrade head

makemigrations:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

lint:
	cd backend && ruff check .
	cd bot && ruff check .
	cd vpn && ruff check .
	cd xray-agent && ruff check .

fmt:
	cd backend && ruff format .
	cd bot && ruff format .
	cd vpn && ruff format .
	cd xray-agent && ruff format .

typecheck:
	cd backend && mypy app
	cd bot && mypy app
	cd vpn && mypy app
	cd xray-agent && mypy app

test: test-backend test-bot test-vpn test-xray-agent

test-backend:
	cd backend && python -m pytest -q

test-bot:
	cd bot && python -m pytest -q

test-vpn:
	cd vpn && python -m pytest -q

test-xray-agent:
	cd xray-agent && python -m pytest -q

e2e-smoke:
	cd backend && python -m pytest ../tests -v

backend-dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

bot-dev:
	cd bot && python -m app.main

frontend-dev:
	cd frontend && npm run dev

expiry-worker:
	$(COMPOSE) exec backend python -m app.workers.run_expiry_worker

create-admin:
	$(COMPOSE) exec backend python -m app.scripts.create_admin --email $(email)

up-prod:
	$(COMPOSE_PROD) up -d --build

down-prod:
	$(COMPOSE_PROD) down

logs-prod:
	$(COMPOSE_PROD) logs -f
