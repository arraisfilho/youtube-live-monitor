"""Container entry point: serve (default), init, reset-password and test."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from backend.app import app_from_env, runtime_config
from backend.collector import MonitorError, State, YouTubeClient, cycle, load_config
from backend.store import Store, cipher_from_secret


def _store() -> Store:
    secret = Path(os.environ.get("YLM_SECRET_FILE", "/run/secrets/app_key")).read_bytes()
    data_dir = Path(os.environ.get("YLM_DATA_DIR", "/data"))
    return Store(str(data_dir / "state.db"), cipher_from_secret(secret))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "init", "reset-password", "test"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command in {"init", "reset-password"}:
            store = _store()
            try:
                if args.command == "init" and store.has_account():
                    print("The account already exists; the password was not changed.")
                    return 0
                password = store.reset_password()
            finally:
                store.close()
            print(f"User: admin\nTemporary password: {password}\nIt must be changed on first sign-in.")
            return 0
        if args.command == "test":
            store = _store()
            cfg = runtime_config(load_config(os.environ.get("YLM_CONFIG")), store)
            store.close()
            client = YouTubeClient(float(cfg["collector"]["timeout"]), int(cfg["collector"]["retries"]))
            state = State(":memory:")
            return 1 if cycle(cfg, state, client, test=True) else 0
        import uvicorn

        os.umask(0o077)
        uvicorn.run(app_from_env(), host="0.0.0.0", port=8000, workers=1, access_log=False, log_config=None,
                    timeout_graceful_shutdown=10)
        return 0
    except (MonitorError, OSError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
