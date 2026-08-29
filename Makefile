.PHONY: install serve test demo chaos reset mcp

install:
	pip install -e ".[dev]"

serve:
	python -m reweave.cli serve

test:
	python -m pytest -q

chaos:
	python -m reweave.cli chaos

reset:
	python -m reweave.cli reset

mcp:
	python -m reweave.cli mcp
