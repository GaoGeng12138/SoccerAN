.PHONY: install test fetch update predict daily clean

install:
	pip install -e ".[dev]"

test:
	pytest -q

fetch:
	python -m socceran fetch

update:
	python -m socceran update

predict:
	python -m socceran predict

daily: fetch update predict

clean:
	rm -rf data/raw/*.csv out/*.csv out/*.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
