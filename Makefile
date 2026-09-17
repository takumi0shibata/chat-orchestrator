.PHONY: setup-backend setup-frontend sandbox-build dev-backend dev-frontend test test-docker release-patch release-minor release-major
setup-backend:
	cd backend && uv sync --frozen
setup-frontend:
	cd frontend && npm ci
sandbox-build:
	docker build -t chat-orchestrator-sandbox:local sandbox
dev-backend:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
dev-frontend:
	cd frontend && npm run dev -- --host 127.0.0.1
test:
	cd backend && uv run pytest -m 'not docker and not live'
	cd frontend && npm test && npm run build
test-docker:
	cd backend && RUN_DOCKER_TESTS=1 uv run pytest -m docker
release-patch:
	./scripts/release.sh patch
release-minor:
	./scripts/release.sh minor
release-major:
	./scripts/release.sh major
