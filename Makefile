.PHONY: install test bench lint clean

install:
	python -m pip install -e ".[numpy,dev]"

test:
	python -m unittest discover -s tests -v

bench:
	PYTHONPATH=src python -m threadwise bench

lint:
	ruff check src tests examples

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
