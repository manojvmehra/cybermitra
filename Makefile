PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python
endif

.PHONY: setup run test probe prerender bench lint smoke

setup:
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt
	ffmpeg -version

run:
	$(PY) -m uvicorn app.main:app --reload --port 8080

test:
	$(PY) -m pytest --cov=app/nlp --cov=app/dialog --cov-report=term-missing

smoke:
	$(PY) scripts/smoke_gnani.py

probe:
	$(PY) scripts/probe_prisma_formats.py --clips 8

prerender:
	$(PY) scripts/prerender_prompts.py

bench:
	$(PY) bench/augment.py
	$(PY) bench/run_benchmark.py
	$(PY) bench/report.py

lint:
	$(PY) -m ruff check app tests scripts bench
	$(PY) -m mypy app/nlp app/dialog
