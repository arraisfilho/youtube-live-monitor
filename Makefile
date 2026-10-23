.PHONY: check lint test validate web

check: lint test validate web

lint:
	python3 -m ruff check backend tests
	bash -n install.sh uninstall.sh
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck install.sh uninstall.sh; else echo "shellcheck not installed; skipped"; fi

test:
	python3 -m pytest

validate:
	python3 -m compileall -q backend
	python3 -c 'import pathlib, yaml; [yaml.safe_load(p.read_text()) for p in map(pathlib.Path, ("compose.yaml", "deploy/victoriametrics/scrape.yml", ".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/dependabot.yml"))]'

web:
	cd frontend && npm ci --no-audit --no-fund && npm run build
