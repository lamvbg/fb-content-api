.PHONY: run dev migrate makemigrations test

run:
	uvicorn machine.server:app --host 0.0.0.0 --port 8000 --reload

dev:
	uvicorn machine.server:app --host 0.0.0.0 --port 8000 --reload

migrate:
	alembic upgrade head

makemigrations:
	alembic revision --autogenerate -m "$(msg)"

downgrade:
	alembic downgrade -1

test:
	pytest tests/ -v

install:
	pip install -r requirements.txt

docker-up:
	docker-compose -f docker/docker-compose.yml up -d

docker-down:
	docker-compose -f docker/docker-compose.yml down
