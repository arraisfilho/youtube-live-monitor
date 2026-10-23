"""Web API, interface and background collector in a single process."""

from __future__ import annotations

import copy
import logging
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import requests
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.collector import (
    API_URL,
    VERSION,
    VIDEO_ID,
    MetricsServer,
    MonitorError,
    State,
    YouTubeClient,
    acquire_lock,
    cycle,
    enabled_video_ids,
    live_view,
    load_config,
    render_metrics,
    sanitize,
)
from backend.store import SESSION_TTL, Store, cipher_from_secret, mask_key

# Interval at which VictoriaMetrics scrapes the collector: each chart point is one reading.
SCRAPE_STEP = 15
# 45,000 points of 15 s cover 7.5 days; VictoriaMetrics runs with a limit of 50,000 per series.
MAX_POINTS = 45_000
MAX_RANGE = 366 * 86400
COOKIE = "ylm_session"
CSRF_HEADER = "x-ylm-request"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://i.ytimg.com; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# Fixed queries by name: the browser never sends PromQL.
LIVE_SERIES = {
    "viewers": 'youtube_live_concurrent_viewers{{video_id="{id}"}}',
    "peak": 'youtube_live_peak_viewers{{video_id="{id}"}}',
    "average": 'youtube_live_average_viewers{{video_id="{id}"}}',
    "elapsed": 'youtube_live_elapsed_seconds{{video_id="{id}"}}',
    "views": 'youtube_live_views{{video_id="{id}"}}',
    "likes": 'youtube_live_likes{{video_id="{id}"}}',
    "comments": 'youtube_live_comments{{video_id="{id}"}}',
    "engagement": 'youtube_live_engagement_rate_percent{{video_id="{id}"}}',
    "viewer_change": 'youtube_live_viewer_change_per_minute{{video_id="{id}"}}',
    "new_views": 'youtube_live_new_views_per_minute{{video_id="{id}"}}',
    "new_likes": 'youtube_live_likes_per_minute{{video_id="{id}"}}',
}
HEALTH_SERIES = {
    "api_calls": "increase(youtube_collector_api_calls_total[{step}s])",
    "live_lives": 'youtube_collector_lives{{status="live"}}',
}
METRIC_FIELDS = (
    "concurrent_viewers", "peak_viewers", "average_viewers", "viewer_change_per_minute", "viewer_change_percent",
    "total_views", "new_views_per_minute", "views_since_start", "like_count", "likes_per_minute", "comment_count",
    "comments_per_minute", "engagement_rate", "elapsed_seconds", "scheduled_delay_seconds", "time_to_peak_seconds",
    "peak_timestamp", "viewer_count_available", "seconds_until_start", "overdue_seconds",
)


class LoginBody(BaseModel):
    password: str = Field(max_length=200)


class PasswordBody(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class LiveBody(BaseModel):
    url: str = Field(min_length=11, max_length=500)


class LivePatch(BaseModel):
    enabled: bool | None = None
    share_enabled: bool | None = None


class SettingsBody(BaseModel):
    daily_quota: int | None = None
    live_interval: int | None = None
    display_timezone: str | None = Field(default=None, max_length=64)


class ApiKeyBody(BaseModel):
    api_key: str = Field(max_length=200)


def runtime_config(base: dict[str, Any], store: Store) -> dict[str, Any]:
    """Cycle configuration: advanced settings from the file plus what was set in the interface."""
    cfg = copy.deepcopy(base)
    settings = store.settings()
    cfg["youtube"]["api_key"] = store.api_key()
    cfg["youtube"]["daily_quota"] = settings["daily_quota"]
    cfg["collector"]["interval"] = float(settings["live_interval"])
    cfg["display_timezone"] = settings["display_timezone"]
    cfg["lives"] = [
        {"url": t["url"], "video_id": t["video_id"], "enabled": bool(t["enabled"])} for t in store.targets()
    ]
    return cfg


class Collector(threading.Thread):
    def __init__(self, db_path: str, cipher: Fernet, base_cfg: dict[str, Any]):
        super().__init__(name="collector", daemon=True)
        self.db_path = db_path
        self.cipher = cipher
        self.base_cfg = base_cfg
        self.stop_event = threading.Event()
        self.last_cycle_at = 0.0

    def run(self) -> None:
        lock = acquire_lock(self.db_path)
        state = State(self.db_path)
        store = Store(self.db_path, self.cipher)
        collector = self.base_cfg["collector"]
        client = YouTubeClient(float(collector["timeout"]), int(collector["retries"]))
        exporter = self.base_cfg["exporter"]
        server = MetricsServer(str(exporter["listen"]), int(exporter["port"]))
        logging.info("Collector %s: internal metrics on %s:%s", VERSION, exporter["listen"], exporter["port"])
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                cfg = runtime_config(self.base_cfg, store)
                try:
                    cycle(cfg, state, client)
                except Exception as exc:
                    logging.error("Cycle interrupted: %s", sanitize(str(exc)))
                    state.db.rollback()
                try:
                    server.text = render_metrics(cfg, state, time.time())
                except Exception as exc:
                    logging.error("Failed to render metrics: %s", exc)
                self.last_cycle_at = time.time()
                self.stop_event.wait(max(0.0, float(cfg["collector"]["interval"]) - (time.monotonic() - started)))
        finally:
            server.httpd.shutdown()
            store.close()
            state.close()
            lock.close()

    def stop(self) -> None:
        self.stop_event.set()


class LoginGuard:
    """Single account: after 5 consecutive failures, an increasing wait of up to 5 min."""

    def __init__(self) -> None:
        self.failures = 0
        self.locked_until = 0.0
        self.lock = threading.Lock()

    def check(self, now: float) -> None:
        with self.lock:
            if now < self.locked_until:
                wait = math.ceil(self.locked_until - now)
                raise HTTPException(429, f"Muitas tentativas. Tente de novo em {wait} s.", {"Retry-After": str(wait)})

    def failed(self, now: float) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= 5:
                self.locked_until = now + min(300, 5 * 2 ** (self.failures - 5))

    def succeeded(self) -> None:
        with self.lock:
            self.failures = 0
            self.locked_until = 0.0


def create_app(
    *, data_dir: str, secret: bytes, vm_url: str, static_dir: str | None = None, config_path: str | None = None,
    start_collector: bool = True, now=time.time,
) -> FastAPI:
    cipher = cipher_from_secret(secret)
    db_path = str(Path(data_dir) / "state.db")
    base_cfg = load_config(config_path)
    Store(db_path, cipher).close()
    State(db_path).close()
    guard = LoginGuard()
    collector = Collector(db_path, cipher, base_cfg) if start_collector else None
    static = Path(static_dir).resolve() if static_dir else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if collector:
            collector.start()
        yield
        if collector:
            collector.stop()

    app = FastAPI(title="YouTube Live Monitor", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.collector = collector

    @app.middleware("http")
    async def _security(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "Requisição recusada"}, status_code=403)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def get_store() -> Iterator[Store]:
        store = Store(db_path, cipher)
        try:
            yield store
        finally:
            store.close()

    def get_state() -> Iterator[State]:
        state = State(db_path)
        try:
            yield state
        finally:
            state.close()

    def authenticated(request: Request, store: Store = Depends(get_store)) -> Store:
        if not store.valid_session(request.cookies.get(COOKIE), now()):
            raise HTTPException(401, "Sessão expirada. Entre de novo.")
        return store

    def user(store: Store = Depends(authenticated)) -> Store:
        if store.must_change_password():
            raise HTTPException(403, "password_change_required")
        return store

    def https(request: Request) -> bool:
        return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

    def tz(store: Store) -> ZoneInfo:
        return ZoneInfo(store.settings()["display_timezone"])

    def live_payload(target: dict[str, Any], view: dict[str, Any], *, private: bool) -> dict[str, Any]:
        video_id = target["video_id"]
        payload = {
            "video_id": video_id,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "title": view.get("title") or "",
            "channel_name": view.get("channel_name") or "",
            "display_name": view.get("display_name") or video_id,
            "status": int(view.get("status") or 0),
            "status_name": view.get("status_name") or "unknown",
            "scheduled_start": view.get("scheduled_start") or None,
            "actual_start": view.get("actual_start") or None,
            "actual_end": view.get("actual_end") or None,
            "last_update": view.get("last_update"),
            "metrics": {key: view.get(key) for key in METRIC_FIELDS},
        }
        if private:
            token = target.get("share_token")
            payload.update({
                "url": target["url"],
                "enabled": bool(target["enabled"]),
                "share_enabled": bool(target["share_enabled"]),
                "share_path": f"/p/{token}" if token and target["share_enabled"] else None,
            })
        return payload

    def series(exprs: dict[str, str], range_s: int | None, start: float | None, end: float | None,
               **fmt: str) -> dict[str, Any]:
        """Every 15 s reading while it fits in MAX_POINTS; beyond that, grouped points (`aggregated`)."""
        moment = now()
        if start is not None and end is not None:
            end = min(float(end), moment)
            start = float(start)
            if end - start < 60:
                raise HTTPException(400, "O período precisa ter pelo menos 1 minuto")
        else:
            end = moment
            start = end - max(300, min(int(range_s or 1800), MAX_RANGE))
        if end - start > MAX_RANGE:
            raise HTTPException(400, "O período pode ter no máximo 366 dias")
        span = end - start
        step = SCRAPE_STEP if span / SCRAPE_STEP <= MAX_POINTS else math.ceil(span / MAX_POINTS / SCRAPE_STEP) * SCRAPE_STEP
        result: dict[str, list[list[float]]] = {}
        for name, template in exprs.items():
            try:
                response = requests.get(
                    f"{vm_url}/api/v1/query_range",
                    params={"query": template.format(step=step, **fmt), "start": start, "end": end, "step": step},
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()["data"]["result"]
            except (requests.RequestException, ValueError, KeyError) as exc:
                raise HTTPException(503, "Histórico indisponível no momento") from exc
            values = data[0]["values"] if data else []
            result[name] = [[float(ts), float(value)] for ts, value in values if value not in {"NaN", "+Inf", "-Inf"}]
        return {"step": step, "start": start, "end": end, "range": span, "aggregated": step > SCRAPE_STEP,
                "series": result}

    def find_target(store: Store, video_id: str) -> dict[str, Any]:
        if not VIDEO_ID.fullmatch(video_id):
            raise HTTPException(404, "Live não encontrada")
        target = store.target(video_id)
        if not target:
            raise HTTPException(404, "Live não encontrada")
        return target

    # -------------------------------------------------------------- session
    @app.get("/api/healthz")
    def healthz() -> dict[str, Any]:
        alive = collector is None or collector.is_alive()
        if not alive:
            raise HTTPException(503, "Coletor parado")
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request, store: Store = Depends(get_store)) -> dict[str, Any]:
        ok = store.valid_session(request.cookies.get(COOKIE), now())
        return {"authenticated": ok, "must_change_password": ok and store.must_change_password(), "version": VERSION}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response, store: Store = Depends(get_store)):
        guard.check(now())
        if not store.has_account() or not store.verify_password(body.password):
            guard.failed(now())
            raise HTTPException(401, "Senha incorreta")
        guard.succeeded()
        token = store.create_session(now())
        response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                            secure=https(request), path="/")
        return {"must_change_password": store.must_change_password()}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, store: Store = Depends(get_store)):
        store.delete_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/password")
    def change_password(body: PasswordBody, request: Request, response: Response,
                        store: Store = Depends(authenticated)):
        if not store.verify_password(body.current):
            raise HTTPException(400, "A senha atual não confere")
        if body.new == body.current:
            raise HTTPException(400, "A nova senha precisa ser diferente da atual")
        try:
            store.set_password(body.new, must_change=False)
        except MonitorError as exc:
            raise HTTPException(400, str(exc)) from exc
        token = store.create_session(now())
        response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                            secure=https(request), path="/")
        return {"ok": True}

    # -------------------------------------------------------------- lives
    @app.get("/api/lives")
    def list_lives(store: Store = Depends(user), state: State = Depends(get_state)) -> list[dict[str, Any]]:
        zone, moment = tz(store), now()
        return [live_payload(t, live_view(state, t["video_id"], moment, zone), private=True) for t in store.targets()]

    @app.post("/api/lives", status_code=201)
    def add_live(body: LiveBody, store: Store = Depends(user), state: State = Depends(get_state)):
        try:
            target = store.add_target(body.url)
        except MonitorError as exc:
            raise HTTPException(400, str(exc)) from exc
        return live_payload(target, live_view(state, target["video_id"], now(), tz(store)), private=True)

    @app.get("/api/lives/{video_id}")
    def get_live(video_id: str, store: Store = Depends(user), state: State = Depends(get_state)):
        target = find_target(store, video_id)
        return live_payload(target, live_view(state, video_id, now(), tz(store)), private=True)

    @app.patch("/api/lives/{video_id}")
    def patch_live(video_id: str, body: LivePatch, store: Store = Depends(user), state: State = Depends(get_state)):
        find_target(store, video_id)
        target = store.update_target(video_id, enabled=body.enabled, share_enabled=body.share_enabled)
        return live_payload(target, live_view(state, video_id, now(), tz(store)), private=True)

    @app.post("/api/lives/{video_id}/share-token")
    def rotate_share(video_id: str, store: Store = Depends(user), state: State = Depends(get_state)):
        find_target(store, video_id)
        target = store.rotate_share_token(video_id)
        return live_payload(target, live_view(state, video_id, now(), tz(store)), private=True)

    @app.delete("/api/lives/{video_id}", status_code=204)
    def delete_live(video_id: str, store: Store = Depends(user)) -> Response:
        find_target(store, video_id)
        store.delete_target(video_id)
        return Response(status_code=204)

    @app.get("/api/lives/{video_id}/series")
    def live_series(video_id: str, range: int | None = None, start: float | None = None,  # noqa: A002
                    end: float | None = None, store: Store = Depends(user)):
        find_target(store, video_id)
        return series(LIVE_SERIES, range, start, end, id=video_id)

    # -------------------------------------------------------------- public
    @app.get("/api/public/{token}")
    def public_live(token: str, store: Store = Depends(get_store), state: State = Depends(get_state)):
        target = store.shared_target(token) if len(token) <= 64 else None
        if not target:
            raise HTTPException(404, "Link indisponível")
        return live_payload(target, live_view(state, target["video_id"], now(), tz(store)), private=False)

    @app.get("/api/public/{token}/series")
    def public_series(token: str, range: int | None = None, start: float | None = None,  # noqa: A002
                      end: float | None = None, store: Store = Depends(get_store)):
        target = store.shared_target(token) if len(token) <= 64 else None
        if not target:
            raise HTTPException(404, "Link indisponível")
        return series(LIVE_SERIES, range, start, end, id=target["video_id"])

    # -------------------------------------------------------------- health
    @app.get("/api/health")
    def health(store: Store = Depends(user), state: State = Depends(get_state)) -> dict[str, Any]:
        cfg = runtime_config(base_cfg, store)
        moment = now()
        data = state.health(enabled_video_ids(cfg), moment)
        paused_until = data.pop("quota_paused_until")
        return {
            **data,
            "lives": {**data["lives"], "enabled": len(enabled_video_ids(cfg)), "registered": len(cfg["lives"])},
            "quota": {"used": data["api_calls_today"], "limit": cfg["youtube"]["daily_quota"],
                      "paused": paused_until > moment, "paused_until": paused_until if paused_until > moment else None},
            "api_key_configured": bool(cfg["youtube"]["api_key"]),
            "collector": {
                "version": VERSION, "interval": cfg["collector"]["interval"],
                "alive": collector is None or collector.is_alive(),
                "last_cycle_at": collector.last_cycle_at if collector else None,
            },
        }

    @app.get("/api/health/series")
    def health_series(range: int | None = None, start: float | None = None,  # noqa: A002
                      end: float | None = None, store: Store = Depends(user)):
        return series(HEALTH_SERIES, range, start, end)

    # -------------------------------------------------------------- settings
    def settings_payload(store: Store) -> dict[str, Any]:
        key = store.api_key()
        return {**store.settings(), "api_key": {"configured": bool(key), "masked": mask_key(key) if key else None}}

    @app.get("/api/settings")
    def get_settings(store: Store = Depends(user)) -> dict[str, Any]:
        return settings_payload(store)

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, store: Store = Depends(user)) -> dict[str, Any]:
        try:
            store.update_settings(body.model_dump(exclude_none=True))
        except MonitorError as exc:
            raise HTTPException(400, str(exc)) from exc
        return settings_payload(store)

    @app.put("/api/settings/api-key")
    def put_api_key(body: ApiKeyBody, store: Store = Depends(user)) -> dict[str, Any]:
        try:
            store.set_api_key(body.api_key)
        except MonitorError as exc:
            raise HTTPException(400, str(exc)) from exc
        return settings_payload(store)

    @app.delete("/api/settings/api-key")
    def delete_api_key(store: Store = Depends(user)) -> dict[str, Any]:
        store.clear_api_key()
        return settings_payload(store)

    @app.post("/api/settings/api-key/test")
    def test_api_key(store: Store = Depends(user)) -> dict[str, Any]:
        key = store.api_key()
        if not key:
            raise HTTPException(400, "Nenhuma chave cadastrada")
        try:
            response = requests.get(API_URL, params={"part": "id", "id": "dQw4w9WgXcQ"},
                                    headers={"X-Goog-Api-Key": key}, timeout=10)
        except requests.RequestException as exc:
            raise HTTPException(502, "Não foi possível falar com a YouTube API") from exc
        if response.status_code == 200:
            return {"ok": True, "message": "Chave válida"}
        reason, message = YouTubeClient._error(response)
        return {"ok": False, "message": f"{reason}: {message}" if message else reason}

    # -------------------------------------------------------------- interface
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/") or static is None:
            raise HTTPException(404, "Não encontrado")
        candidate = (static / path).resolve()
        if path and candidate.is_file() and static in candidate.parents:
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
            return FileResponse(candidate, headers=headers)
        index = static / "index.html"
        if not index.is_file():
            raise HTTPException(404, "Página não compilada")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def app_from_env() -> FastAPI:
    secret_file = os.environ.get("YLM_SECRET_FILE", "/run/secrets/app_key")
    try:
        secret = Path(secret_file).read_bytes()
    except OSError as exc:
        raise MonitorError(f"Application secret missing at {secret_file}") from exc
    return create_app(
        data_dir=os.environ.get("YLM_DATA_DIR", "/data"),
        secret=secret,
        vm_url=os.environ.get("YLM_VM_URL", "http://victoriametrics:8428").rstrip("/"),
        static_dir=os.environ.get("YLM_STATIC_DIR", "/app/frontend/dist"),
        config_path=os.environ.get("YLM_CONFIG", "/etc/youtube-live-monitor/config.yaml"),
    )

