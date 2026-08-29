.PHONY: install run test lint check

install:
	python -m pip install -r requirements-dev.txt

run:
	flask --app wsgi:app run --debug --port 8000

test:
	pytest -q

lint:
	ruff check .

check: lint test
