# Contributing

Issues and pull requests are welcome at https://github.com/arraisfilho/youtube-live-monitor.

## Environment

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make check
```

`make check` runs ruff, pytest, `bash -n`, shellcheck (when installed), validates the YAML files and builds the interface (`npm ci` and `npm run build` in `frontend/`).

Full stack: `./install.sh`. Interface in development mode: `cd frontend && npm run dev`.

## Pull requests

Branch from `main`, one change per pull request, tests for new behavior and `make check` passing. The code must keep running on Python 3.12.

New interface text uses the Portuguese text as the key in `t()` and needs its translation in `frontend/src/locales/en.json` and `es.json`.

Never include keys, tokens, private IDs, production logs, databases or real configuration in a diff.

## Issues

Include the version, the operating system, what you did and what happened. Paste error messages after replacing keys, tokens, internal domains, IPs and IDs with placeholders.
