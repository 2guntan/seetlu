# Seetlu developer commands. See README.md.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PY_PACKAGES := backend edge/agent edge/fake-frigate
COMPOSE := docker compose
SERVICES := db redis minio api worker beat mock-whatsapp web mosquitto fake-frigate agent

.PHONY: help env install up down logs ps migrate seed test lint fmt sim-day report e2e

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

env: .env ## Create .env from .env.example if missing

install: ## Install local dev dependencies (uv + npm)
	@for p in $(PY_PACKAGES); do (cd $$p && uv sync -q) || exit 1; done
	cd web && npm ci --silent

up: .env ## Start the dev stack (postgres, redis, minio, api, worker, beat, web, mock-whatsapp, mosquitto, fake-frigate, agent)
	$(COMPOSE) up -d --build --wait --wait-timeout 300 $(SERVICES)
	$(COMPOSE) run --rm --build minio-init
	@echo "api http://localhost:8000/docs | web http://localhost:5173 | mock WhatsApp http://localhost:8025/messages | minio http://localhost:9001"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Follow logs
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## alembic upgrade head
	$(COMPOSE) run --rm api alembic upgrade head

seed: migrate ## Demo data (runs migrations first; idempotent)
	$(COMPOSE) run --rm api python -m seetlu.seed

lint: ## ruff + mypy --strict, eslint + tsc
	@for p in $(PY_PACKAGES); do echo "== lint $$p"; (cd $$p && uv run ruff check . && uv run ruff format --check . && uv run mypy .) || exit 1; done
	@echo "== lint web"; cd web && npm run -s lint && npm run -s typecheck

fmt: ## Auto-format Python
	@for p in $(PY_PACKAGES); do (cd $$p && uv run ruff check --fix -q . && uv run ruff format -q .); done

test: ## All test suites
	@for p in $(PY_PACKAGES); do echo "== test $$p"; (cd $$p && uv run pytest -q) || exit 1; done
	@echo "== test web"; cd web && npm test -s

SCENARIO ?= normal-day
sim-day: ## make sim-day SHOP=<shop id|kit serial> DATE=YYYY-MM-DD [SCENARIO=normal-day]
	@test -n "$(SHOP)" -a -n "$(DATE)" || { echo "usage: make sim-day SHOP=<shop id> DATE=YYYY-MM-DD [SCENARIO=normal-day]"; exit 2; }
	@serial=$$($(COMPOSE) run --rm -T api python -m seetlu.seed.kit_serial "$(SHOP)") || exit 1; \
	echo "sim-day: scenario $(SCENARIO) on $(DATE) for kit $$serial (the real agent, simulator clock)"; \
	$(COMPOSE) stop agent >/dev/null 2>&1; \
	docker container inspect seetlu-sim-agent >/dev/null 2>&1 && docker container stop seetlu-sim-agent >/dev/null; \
	docker container prune -f --filter label=com.docker.compose.oneoff=True >/dev/null; \
	$(COMPOSE) run -d --name seetlu-sim-agent -e KIT_SERIAL=$$serial -e AGENT_DATA_DIR=/data/sim-$$serial \
	  agent seetlu-agent replay 15 >/dev/null || exit 1; \
	sleep 3; \
	curl -fsS -X POST "http://localhost:5050/sim/scenarios/$(SCENARIO)/run?speed=0&day=$(DATE)" >/dev/null || exit 1; \
	code=$$(docker wait seetlu-sim-agent 2>/dev/null || echo 1); \
	docker logs seetlu-sim-agent 2>&1 | grep -E "replay done|ERROR" | tail -3; \
	docker container rm seetlu-sim-agent >/dev/null 2>&1; \
	$(COMPOSE) start agent >/dev/null 2>&1; \
	test "$$code" = 0 && echo "sim-day: done (events and heartbeats uploaded)" || { echo "sim-day: agent exited with $$code"; exit 1; }

report: ## make report SHOP=<id> DATE=YYYY-MM-DD (lands in M6)
	@test -n "$(SHOP)" -a -n "$(DATE)" || { echo "usage: make report SHOP=<id> DATE=YYYY-MM-DD"; exit 2; }
	@echo "report: report engine lands in M6"; exit 1

e2e: ## End-to-end normal-day scenario (lands in M7)
	@echo "e2e: lands with M6/M7"; exit 1
