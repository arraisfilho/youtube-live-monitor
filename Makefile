.PHONY: check lint test validate

check: lint test validate

lint:
	python3 -m ruff check youtube_live_monitor.py tests
	bash -n install.sh uninstall.sh
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck install.sh uninstall.sh; else echo "shellcheck não instalado; etapa ignorada"; fi

test:
	python3 -m pytest

validate:
	python3 -m compileall -q youtube_live_monitor.py
	python3 -m json.tool grafana_dashboard_youtube_live.json >/dev/null
	python3 -c 'import pathlib, yaml; [yaml.safe_load(p.read_text()) for p in map(pathlib.Path, ("config.example.yaml", "lives.example.yaml", "zabbix_template_youtube_live.yaml", "grafana-youtube-live-provider.yaml"))]'
