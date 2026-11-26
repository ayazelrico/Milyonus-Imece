# Milyonus Agent — developer convenience targets.
.PHONY: sync test docker-test lint fmt typecheck check hooks build web-build docker-build docker-run poison safety chaos

sync:        ## install deps (matches CI: dev + admin + discord)
	uv sync --extra dev --extra admin --extra discord

hooks:       ## enable the versioned git hooks (pre-push runs `make check`)
	git config core.hooksPath .githooks
	@echo "✓ git hooks enabled (.githooks). Pushes now run 'make check' first."

test:        ## run the test suite
	uv run pytest -q

docker-test: ## run the full test suite including real Docker isolation tests
	MILYONUS_TEST_DOCKER=1 uv run pytest -q

lint:        ## lint
	uv run ruff check src tests evals

fmt:         ## format
	uv run ruff format src tests evals

typecheck:   ## run mypy across src/milyonus
	uv run mypy src/milyonus

check: lint typecheck safety chaos  ## lint + format-check + typecheck + safety + chaos + test
	uv run ruff format --check src tests evals
	uv run pytest -q

build:       ## build the wheel
	uv build

web-build:   ## typecheck and build the React web SPA
	cd web && npm run build

poison:      ## run PoisonBench (rule-based)
	uv run python -m evals.poisonbench.run

safety:      ## run SafetyRegression
	uv run python -m evals.safety.run

chaos:       ## run Adversarial Chaos Autopilot (must score 100/100)
	uv run milyonus chaos run --min-score 100

docker-build:   ## build the hardened image
	docker build -f deploy/Dockerfile -t milyonus/agent:5.5.0 -t milyonus/agent:latest .

docker-run:     ## run a session in the container (mounts a data volume)
	docker run --rm -it \
	  --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
	  -v milyonus-data:/data milyonus/agent:latest doctor
