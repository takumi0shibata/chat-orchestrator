.PHONY: setup-backend setup-frontend dev-backend dev-frontend dev docker-up docker-down release-patch release-minor release-major

setup-backend:
	cd backend && uv venv && . .venv/bin/activate && uv pip install -e .

setup-frontend:
	cd frontend && npm install

dev-backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

dev:
	@echo "Run backend and frontend in separate terminals: make dev-backend / make dev-frontend"

docker-up:
	docker compose up --build

docker-down:
	docker compose down

release-patch:
	./scripts/release.sh patch

release-minor:
	./scripts/release.sh minor

release-major:
	./scripts/release.sh major
