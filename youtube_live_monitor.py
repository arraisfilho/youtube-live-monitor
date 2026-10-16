#!/usr/bin/env python3
"""Monitor public YouTube live streams and expose metrics for VictoriaMetrics/Prometheus."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import math
import os
import re
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import yaml

VERSION = "2.0.0"
DEFAULT_CONFIG = "/etc/youtube-live-monitor/config.yaml"
DEFAULT_DB = "/var/lib/youtube-live-monitor/state.db"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
# A quota diária da YouTube Data API vira à meia-noite do Pacífico.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


class MonitorError(RuntimeError):
    """Configuration or integration error with a user-actionable message."""


class QuotaExceeded(MonitorError):
    """The daily YouTube Data API quota is exhausted."""


STATUS = {"unknown": 0, "scheduled": 1, "live": 2, "ended": 3, "unavailable": 4}
STATUS_NAMES = {value: name for name, value in STATUS.items()}

# metric name: (help, key in the live snapshot)
LIVE_METRICS: dict[str, tuple[str, str]] = {
    "youtube_live_status": (
        "Estado: 0 desconhecida, 1 agendada, 2 ao vivo, 3 encerrada, 4 indisponível", "status"),
    "youtube_live_concurrent_viewers": ("Audiência simultânea", "concurrent_viewers"),
    "youtube_live_peak_viewers": ("Pico de audiência simultânea", "peak_viewers"),
    "youtube_live_average_viewers": ("Média das amostras de audiência", "average_viewers"),
    "youtube_live_viewer_change_per_minute": ("Variação de espectadores por minuto", "viewer_change_per_minute"),
    "youtube_live_viewer_change_percent": ("Variação percentual de espectadores em 1 minuto", "viewer_change_percent"),
    "youtube_live_views": ("Visualizações totais do vídeo", "total_views"),
    "youtube_live_new_views_per_minute": ("Novas visualizações por minuto", "new_views_per_minute"),
    "youtube_live_views_since_start": ("Visualizações ganhas desde o início da live", "views_since_start"),
    "youtube_live_likes": ("Curtidas", "like_count"),
    "youtube_live_likes_per_minute": ("Novas curtidas por minuto", "likes_per_minute"),
    "youtube_live_comments": ("Comentários", "comment_count"),
    "youtube_live_comments_per_minute": ("Novos comentários por minuto", "comments_per_minute"),
    "youtube_live_engagement_rate_percent": ("Curtidas por visualização, em %", "engagement_rate"),
    "youtube_live_elapsed_seconds": ("Tempo desde o início real", "elapsed_seconds"),
    "youtube_live_start_delay_seconds": ("Início real menos início agendado", "scheduled_delay_seconds"),
    "youtube_live_time_to_peak_seconds": ("Tempo do início até o pico", "time_to_peak_seconds"),
    "youtube_live_peak_timestamp_seconds": ("Momento do pico (unix)", "peak_timestamp"),
    "youtube_live_viewer_count_available": ("1 se o YouTube informa a audiência simultânea", "viewer_count_available"),
    "youtube_live_seconds_until_start": ("Segundos até o início agendado", "seconds_until_start"),
    "youtube_live_overdue_seconds": ("Segundos de atraso de uma live ainda agendada", "overdue_seconds"),
    "youtube_live_scheduled_start_timestamp_seconds": ("Início agendado (unix)", "scheduled_start_ts"),
    "youtube_live_scheduled_end_timestamp_seconds": ("Fim agendado (unix)", "scheduled_end_ts"),
    "youtube_live_actual_start_timestamp_seconds": ("Início real (unix)", "actual_start_ts"),
    "youtube_live_actual_end_timestamp_seconds": ("Fim real (unix)", "actual_end_ts"),
    "youtube_live_last_update_timestamp_seconds": ("Última consulta bem-sucedida (unix)", "last_update"),
    "youtube_live_api_latency_seconds": ("Latência da última chamada à API", "api_latency"),
    "youtube_live_api_status": ("Código HTTP da última chamada à API", "api_status"),
}

DEFAULT_POLL_POLICY = {
    "more_than_24h": 21600,
    "more_than_6h": 3600,
    "more_than_1h": 900,
    "more_than_15m": 300,
    "near_start": 60,
    "overdue": 30,
    "overdue_after_1h": 300,
    "overdue_after_6h": 3600,
    "overdue_after_48h": 21600,
}


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def extract_video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split(":", 1)[0].removeprefix("www.").removeprefix("m.")
    parts = [part for part in parsed.path.split("/") if part]
    candidate = ""
    if host == "youtu.be":
        candidate = parts[0] if parts else ""
    elif host in {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if parsed.path.rstrip("/") == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) > 1 and parts[0] in {"live", "shorts", "embed", "v", "e"}:
            candidate = parts[1]
    elif host == "studio.youtube.com" and len(parts) > 1 and parts[0] == "video":
        candidate = parts[1]
    if not VIDEO_ID.fullmatch(candidate):
        raise MonitorError(f"Video ID inválido: {value}")
    return candidate


def _positive_number(value: Any, path: str, *, minimum: float = 0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MonitorError(f"{path} deve ser numérico") from exc
    if result < minimum:
        raise MonitorError(f"{path} deve ser >= {minimum:g}")
    return result


def normalize_live_entries(entries: Any, source: str) -> list[dict[str, Any]]:
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise MonitorError(f"A lista de lives em {source} deve ser uma lista YAML")
    normalized = []
    for index, live in enumerate(entries, start=1):
        if isinstance(live, str):
            live = {"url": live}
        if not isinstance(live, dict) or not live.get("url"):
            raise MonitorError(f"Live inválida em {source}, posição {index}")
        enabled = live.get("enabled", True)
        if not isinstance(enabled, bool):
            raise MonitorError(f"enabled deve ser true ou false sem aspas em {source}, posição {index}")
        extract_video_id(str(live["url"]))
        normalized.append({**live, "enabled": enabled})
    return normalized


def load_lives_file(path: str) -> list[dict[str, Any]]:
    lives_path = Path(path)
    if not lives_path.is_absolute():
        raise MonitorError("lives_file deve usar um caminho absoluto")
    if not lives_path.is_file():
        raise MonitorError(f"Arquivo de lives não encontrado: {path}")
    try:
        data = yaml.safe_load(lives_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MonitorError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MonitorError("lives_file deve conter um mapa com a chave 'lives'")
    return normalize_live_entries(data.get("lives"), path)


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).resolve()
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MonitorError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise MonitorError("A raiz do YAML deve ser um mapa")
    for section in ("youtube", "collector", "exporter"):
        if cfg.get(section) is None:
            cfg[section] = {}
        if not isinstance(cfg[section], dict):
            raise MonitorError(f"A seção {section} deve ser um mapa YAML")
    env_map = {
        "YOUTUBE_API_KEY": ("youtube", "api_key", str),
        "YOUTUBE_API_KEY_FILE": ("youtube", "api_key_file", str),
        "EXPORTER_LISTEN": ("exporter", "listen", str),
        "EXPORTER_PORT": ("exporter", "port", int),
    }
    for env, (section, key, cast) in env_map.items():
        if os.environ.get(env):
            try:
                cfg[section][key] = cast(os.environ[env])
            except ValueError as exc:
                raise MonitorError(f"Valor inválido em {env}") from exc
    if os.environ.get("YOUTUBE_LIVES_FILE"):
        cfg["lives_file"] = os.environ["YOUTUBE_LIVES_FILE"]
    if os.environ.get("DISPLAY_TIMEZONE"):
        cfg["display_timezone"] = os.environ["DISPLAY_TIMEZONE"]

    youtube = cfg["youtube"]
    youtube["daily_quota"] = int(_positive_number(youtube.get("daily_quota", 10000), "youtube.daily_quota", minimum=1))

    collector = cfg["collector"]
    defaults = {
        "interval": 15, "timeout": 10, "retries": 2, "batch_size": 50, "unknown_interval": 300,
        "unavailable_interval": 1800, "error_backoff_initial": 300, "error_backoff_max": 3600,
        "log_api_state": False,
    }
    for key, default in defaults.items():
        collector.setdefault(key, default)
    policy = collector.setdefault("schedule_poll", {})
    if not isinstance(policy, dict):
        raise MonitorError("collector.schedule_poll deve ser um mapa")
    for key, default in DEFAULT_POLL_POLICY.items():
        policy.setdefault(key, default)
    collector["interval"] = _positive_number(collector["interval"], "collector.interval", minimum=5)
    collector["timeout"] = _positive_number(collector["timeout"], "collector.timeout", minimum=1)
    collector["retries"] = int(_positive_number(collector["retries"], "collector.retries"))
    collector["batch_size"] = int(_positive_number(collector["batch_size"], "collector.batch_size", minimum=1))
    if collector["batch_size"] > 50:
        raise MonitorError("collector.batch_size deve estar entre 1 e 50")
    for key in ("unknown_interval", "unavailable_interval", "error_backoff_initial", "error_backoff_max"):
        collector[key] = _positive_number(collector[key], f"collector.{key}", minimum=30)
    if collector["error_backoff_max"] < collector["error_backoff_initial"]:
        raise MonitorError("collector.error_backoff_max deve ser >= error_backoff_initial")
    if not isinstance(collector["log_api_state"], bool):
        raise MonitorError("collector.log_api_state deve ser true ou false sem aspas")
    for key in DEFAULT_POLL_POLICY:
        policy[key] = _positive_number(policy[key], f"collector.schedule_poll.{key}", minimum=15)

    exporter = cfg["exporter"]
    exporter.setdefault("listen", "127.0.0.1")
    exporter["port"] = int(_positive_number(exporter.get("port", 9877), "exporter.port", minimum=1))
    if exporter["port"] > 65535:
        raise MonitorError("exporter.port fora do intervalo válido")

    tz_name = str(cfg.get("display_timezone") or os.environ.get("TZ") or "UTC")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise MonitorError(f"display_timezone inválido: {tz_name}") from exc
    cfg["display_timezone"] = tz_name

    lives: list[dict[str, Any]] = []
    if cfg.get("lives_file"):
        lives_path = Path(str(cfg["lives_file"]))
        if not lives_path.is_absolute():
            lives_path = config_path.parent / lives_path
        cfg["lives_file"] = str(lives_path.resolve())
        lives.extend(load_lives_file(cfg["lives_file"]))
    lives.extend(normalize_live_entries(cfg.get("lives"), path))

    merged: dict[str, dict[str, Any]] = {}
    for live in lives:
        video_id = extract_video_id(str(live["url"]))
        if video_id in merged:
            merged[video_id]["enabled"] = merged[video_id]["enabled"] or live["enabled"]
        else:
            merged[video_id] = {**live, "video_id": video_id}
    cfg["lives"] = list(merged.values())
    cfg["_config_path"] = str(config_path)
    return cfg


def resolve_api_key(cfg: dict[str, Any]) -> str:
    youtube = cfg.get("youtube", {})
    key_file = youtube.get("api_key_file")
    if key_file:
        try:
            key = Path(str(key_file)).read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
        if key:
            return key
    return str(youtube.get("api_key") or "").strip()


def credential_warnings(cfg: dict[str, Any]) -> list[str]:
    key = resolve_api_key(cfg)
    if not key:
        return ["Chave da YouTube API ausente (youtube.api_key, YOUTUBE_API_KEY ou arquivo api_key_file)"]
    if any(marker in key.upper() for marker in ("SUA_", "YOUR_", "CHANGE_ME", "XXXXXXXX")):
        return ["A chave da YouTube API ainda é o valor de exemplo"]
    return []


def quota_day(now: float) -> str:
    return datetime.fromtimestamp(now, QUOTA_TZ).date().isoformat()


def next_quota_reset(now: float) -> float:
    local = datetime.fromtimestamp(now, QUOTA_TZ)
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=QUOTA_TZ)
    return midnight.timestamp()


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS lives (
                video_id TEXT PRIMARY KEY, channel_id TEXT, channel_name TEXT, title TEXT,
                scheduled_start TEXT, actual_start TEXT, actual_end TEXT,
                status INTEGER NOT NULL DEFAULT 0, last_view_count INTEGER,
                last_concurrent_viewers INTEGER, peak_viewers INTEGER NOT NULL DEFAULT 0,
                viewer_sum INTEGER NOT NULL DEFAULT 0, viewer_samples INTEGER NOT NULL DEFAULT 0,
                last_collection REAL, last_like_count INTEGER, last_comment_count INTEGER,
                peak_timestamp REAL, scheduled_end TEXT
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS samples (
                video_id TEXT, collected_at REAL, viewers INTEGER, views INTEGER, likes INTEGER
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS poll_schedule (
                video_id TEXT PRIMARY KEY, next_poll REAL NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0,
                last_attempt REAL, last_success REAL, last_status INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS collector_counters (
                key TEXT PRIMARY KEY, value REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS api_usage (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0
            )"""
        )
        for table, column, definition in (
            ("lives", "last_like_count", "INTEGER"),
            ("lives", "last_comment_count", "INTEGER"),
            ("lives", "peak_timestamp", "REAL"),
            ("lives", "scheduled_end", "TEXT"),
            ("lives", "first_view_count", "INTEGER"),
            ("lives", "snapshot", "TEXT"),
            ("samples", "likes", "INTEGER"),
            ("samples", "comments", "INTEGER"),
            ("poll_schedule", "last_status", "INTEGER NOT NULL DEFAULT 0"),
        ):
            self._ensure_column(table, column, definition)
        self.db.execute("CREATE INDEX IF NOT EXISTS samples_lookup ON samples(video_id, collected_at)")
        self.db.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        self.db.close()

    def _schedule(self, video_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM poll_schedule WHERE video_id=?", (video_id,)).fetchone()

    def is_due(self, video_id: str, now: float) -> bool:
        row = self._schedule(video_id)
        return row is None or (not row["finalized"] and row["next_poll"] <= now)

    def is_adaptively_deferred(self, video_id: str, now: float) -> bool:
        row = self._schedule(video_id)
        return bool(row and not row["finalized"] and row["failure_count"] == 0 and row["next_poll"] > now)

    def last_status(self, video_id: str) -> int | None:
        row = self._schedule(video_id)
        return int(row["last_status"]) if row is not None else None

    def mark_attempt(self, video_id: str, now: float) -> None:
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, last_attempt) VALUES(?, ?)
               ON CONFLICT(video_id) DO UPDATE SET last_attempt=excluded.last_attempt""",
            (video_id, now),
        )

    @staticmethod
    def next_interval(info: dict[str, Any], collector: dict[str, Any], now: float) -> float:
        status = int(info.get("status", 0))
        if status == STATUS["live"]:
            return float(collector["interval"])
        if status == STATUS["scheduled"]:
            scheduled = parse_iso(info.get("scheduled_start"))
            if scheduled is None:
                return float(collector["unknown_interval"])
            until = scheduled - now
            policy = collector["schedule_poll"]
            if until > 86400:
                return float(policy["more_than_24h"])
            if until > 21600:
                return float(policy["more_than_6h"])
            if until > 3600:
                return float(policy["more_than_1h"])
            if until > 900:
                return float(policy["more_than_15m"])
            if until > 0:
                return float(policy["near_start"])
            overdue = -until
            if overdue <= 3600:
                return float(policy["overdue"])
            if overdue <= 21600:
                return float(policy["overdue_after_1h"])
            if overdue <= 172800:
                return float(policy["overdue_after_6h"])
            return float(policy["overdue_after_48h"])
        return float(collector["unknown_interval"])

    def mark_success(self, video_id: str, info: dict[str, Any], collector: dict[str, Any], now: float) -> None:
        status = int(info.get("status", 0))
        previous = self.last_status(video_id)
        ended = status == STATUS["ended"]
        # Encerramento só é definitivo com actualEndTime ou após duas leituras seguidas.
        finalized = ended and (bool(info.get("actual_end")) or previous == STATUS["ended"])
        interval = 60.0 if ended and not finalized else self.next_interval(info, collector, now)
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, next_poll, failure_count, finalized,
                                            last_attempt, last_success, last_status)
               VALUES(?, ?, 0, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET next_poll=excluded.next_poll,
                   failure_count=0, finalized=excluded.finalized,
                   last_attempt=excluded.last_attempt, last_success=excluded.last_success,
                   last_status=excluded.last_status""",
            (video_id, now + interval, int(finalized), now, now, status),
        )

    def mark_failure(self, video_id: str, collector: dict[str, Any], now: float) -> None:
        row = self._schedule(video_id)
        failures = (int(row["failure_count"]) if row else 0) + 1
        delay = min(
            float(collector["error_backoff_max"]),
            float(collector["error_backoff_initial"]) * (2 ** (failures - 1)),
        )
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, next_poll, failure_count, last_attempt)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET next_poll=excluded.next_poll,
                   failure_count=excluded.failure_count, last_attempt=excluded.last_attempt""",
            (video_id, now + delay, failures, now),
        )

    def mark_unavailable(self, video_id: str, collector: dict[str, Any], now: float) -> bool:
        """Vídeo privado ou removido: estado próprio, sem contar como erro do coletor."""
        previous = self.last_status(video_id)
        self.db.execute(
            """INSERT INTO poll_schedule(video_id, next_poll, failure_count, last_attempt, last_status)
               VALUES(?, ?, 0, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET next_poll=excluded.next_poll, failure_count=0,
                   last_attempt=excluded.last_attempt, last_status=excluded.last_status""",
            (video_id, now + float(collector["unavailable_interval"]), now, STATUS["unavailable"]),
        )
        snapshot = self.snapshot(video_id) or {"video_id": video_id}
        snapshot.update({"status": STATUS["unavailable"], "concurrent_viewers": None})
        self.db.execute(
            """INSERT INTO lives(video_id, status, snapshot) VALUES(?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET status=excluded.status, snapshot=excluded.snapshot""",
            (video_id, STATUS["unavailable"], json.dumps(snapshot)),
        )
        return previous != STATUS["unavailable"]

    def counter(self, key: str) -> float:
        row = self.db.execute("SELECT value FROM collector_counters WHERE key=?", (key,)).fetchone()
        return float(row["value"]) if row else 0.0

    def increment(self, key: str, amount: float, now: float) -> None:
        self.db.execute(
            """INSERT INTO collector_counters(key, value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=value+excluded.value, updated_at=excluded.updated_at""",
            (key, amount, now),
        )

    def set_value(self, key: str, value: float, now: float) -> None:
        self.db.execute(
            """INSERT INTO collector_counters(key, value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, now),
        )

    def record_api_calls(self, calls: int, videos: int, now: float) -> None:
        if calls <= 0:
            return
        self.db.execute(
            """INSERT INTO api_usage(day, calls) VALUES(?, ?)
               ON CONFLICT(day) DO UPDATE SET calls=calls+excluded.calls""",
            (quota_day(now), calls),
        )
        self.increment("api_calls_total", calls, now)
        self.increment("videos_polled_total", videos, now)

    def api_calls_today(self, now: float) -> int:
        row = self.db.execute("SELECT calls FROM api_usage WHERE day=?", (quota_day(now),)).fetchone()
        return int(row["calls"]) if row else 0

    def snapshot(self, video_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT snapshot FROM lives WHERE video_id=?", (video_id,)).fetchone()
        return json.loads(row["snapshot"]) if row and row["snapshot"] else None

    def update(self, video_id: str, info: dict[str, Any], collector: dict[str, Any], now: float) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM lives WHERE video_id=?", (video_id,)).fetchone()
        viewers = info.get("concurrent_viewers")
        views = info.get("total_views")
        likes = info.get("like_count")
        comments = info.get("comment_count")
        is_live = int(info.get("status", 0)) == STATUS["live"]

        peak = int(row["peak_viewers"]) if row else 0
        total = float(row["viewer_sum"]) if row else 0.0
        samples = int(row["viewer_samples"]) if row else 0
        peak_timestamp = float(row["peak_timestamp"]) if row and row["peak_timestamp"] is not None else None
        first_views = row["first_view_count"] if row else None

        if is_live and viewers is not None:
            if peak_timestamp is None or int(viewers) > peak:
                peak = int(viewers)
                peak_timestamp = now
            total += int(viewers)
            samples += 1
        if is_live and views is not None and first_views is None:
            first_views = int(views)

        window = max(90.0, 3 * float(collector["interval"]))
        previous = self.db.execute(
            """SELECT viewers, views, likes, comments, collected_at FROM samples
               WHERE video_id=? AND collected_at BETWEEN ? AND ?
               ORDER BY ABS(collected_at-?) LIMIT 1""",
            (video_id, now - window, now - 45, now - 60),
        ).fetchone()

        def per_minute(current: Any, before: Any, *, floor: bool = True) -> float | None:
            if previous is None or current is None or before is None:
                return None
            minutes = max((now - float(previous["collected_at"])) / 60.0, 0.01)
            delta = (int(current) - int(before)) / minutes
            return max(0.0, delta) if floor else delta

        viewer_percent = None
        if is_live and previous and viewers is not None and previous["viewers"]:
            viewer_percent = (int(viewers) - int(previous["viewers"])) * 100.0 / int(previous["viewers"])

        if is_live and any(value is not None for value in (viewers, views, likes, comments)):
            self.db.execute(
                "INSERT INTO samples(video_id, collected_at, viewers, views, likes, comments) VALUES(?,?,?,?,?,?)",
                (video_id, now, viewers, views, likes, comments),
            )
            self.db.execute("DELETE FROM samples WHERE collected_at < ?", (now - 172800,))

        scheduled = parse_iso(info.get("scheduled_start"))
        actual = parse_iso(info.get("actual_start"))
        actual_end = parse_iso(info.get("actual_end"))
        has_audience = samples > 0
        snapshot = {
            **info,
            "peak_viewers": peak if has_audience else None,
            "average_viewers": total / samples if has_audience else None,
            "peak_timestamp": int(peak_timestamp) if has_audience and peak_timestamp else None,
            "time_to_peak_seconds": (
                max(0, int(peak_timestamp - actual)) if has_audience and peak_timestamp and actual else None
            ),
            "viewer_change_per_minute": per_minute(viewers, previous and previous["viewers"], floor=False)
            if is_live else None,
            "viewer_change_percent": viewer_percent,
            "new_views_per_minute": per_minute(views, previous and previous["views"]) if is_live else None,
            "likes_per_minute": per_minute(likes, previous and previous["likes"]) if is_live else None,
            "comments_per_minute": per_minute(comments, previous and previous["comments"]) if is_live else None,
            "views_since_start": int(views) - int(first_views) if views is not None and first_views is not None
            else None,
            "engagement_rate": (int(likes) * 100.0 / int(views)) if likes is not None and views else None,
            "scheduled_delay_seconds": actual - scheduled if scheduled is not None and actual is not None else None,
            "scheduled_start_ts": scheduled,
            "scheduled_end_ts": parse_iso(info.get("scheduled_end")),
            "actual_start_ts": actual,
            "actual_end_ts": actual_end,
        }
        self.db.execute(
            """INSERT INTO lives(video_id, channel_id, channel_name, title, scheduled_start,
                                  scheduled_end, actual_start, actual_end, status, last_view_count,
                                  last_concurrent_viewers, peak_viewers, viewer_sum, viewer_samples,
                                  last_collection, last_like_count, last_comment_count, peak_timestamp,
                                  first_view_count, snapshot)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,
                   channel_name=excluded.channel_name, title=excluded.title,
                   scheduled_start=excluded.scheduled_start, scheduled_end=excluded.scheduled_end,
                   actual_start=excluded.actual_start, actual_end=excluded.actual_end,
                   status=excluded.status, last_view_count=excluded.last_view_count,
                   last_concurrent_viewers=excluded.last_concurrent_viewers,
                   peak_viewers=excluded.peak_viewers, viewer_sum=excluded.viewer_sum,
                   viewer_samples=excluded.viewer_samples, last_collection=excluded.last_collection,
                   last_like_count=excluded.last_like_count,
                   last_comment_count=excluded.last_comment_count,
                   peak_timestamp=excluded.peak_timestamp, first_view_count=excluded.first_view_count,
                   snapshot=excluded.snapshot""",
            (
                video_id, info.get("channel_id"), info.get("channel_name"), info.get("title"),
                info.get("scheduled_start"), info.get("scheduled_end"), info.get("actual_start"),
                info.get("actual_end"), info.get("status", 0), views, viewers, peak, total, samples,
                now, likes, comments, peak_timestamp, first_views, json.dumps(snapshot),
            ),
        )
        return snapshot

    def health(self, video_ids: list[str], now: float) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in video_ids)
        rows = (
            self.db.execute(
                f"SELECT failure_count, last_success, last_status, finalized FROM poll_schedule "
                f"WHERE video_id IN ({placeholders})",
                video_ids,
            ).fetchall()
            if video_ids
            else []
        )
        active = [float(row["last_success"]) for row in rows if row["last_success"] and not row["finalized"]]
        db_size = sum(
            Path(f"{self.path}{suffix}").stat().st_size
            for suffix in ("", "-wal", "-shm")
            if Path(f"{self.path}{suffix}").exists()
        )
        counts = {name: 0 for name in STATUS}
        for row in rows:
            counts[STATUS_NAMES.get(int(row["last_status"]), "unknown")] += 1
        counts["unknown"] += len(video_ids) - len(rows)
        return {
            "api_calls_total": int(self.counter("api_calls_total")),
            "videos_polled_total": int(self.counter("videos_polled_total")),
            "api_calls_today": self.api_calls_today(now),
            "scheduled_polls_skipped_total": int(self.counter("scheduled_polls_skipped")),
            "last_success_age": int(now - max(active)) if active else None,
            "consecutive_errors": max((int(row["failure_count"]) for row in rows), default=0),
            "quota_paused_until": self.counter("quota_paused_until"),
            "db_size_bytes": db_size,
            "lives": counts,
        }


class YouTubeClient:
    def __init__(self, timeout: float, retries: int):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.request_count = 0

    def get_many(self, video_ids: list[str], api_key: str) -> tuple[dict[str, dict[str, Any]], float, int]:
        if not video_ids or len(video_ids) > 50:
            raise ValueError("get_many requer entre 1 e 50 IDs")
        params = {"part": "snippet,statistics,liveStreamingDetails", "id": ",".join(video_ids)}
        # A chave vai no header: nunca aparece em URL, exceção ou log.
        headers = {"X-Goog-Api-Key": api_key}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            self.request_count += 1
            try:
                response = self.session.get(API_URL, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = MonitorError(f"YouTube API: falha de rede ({type(exc).__name__})")
            else:
                latency = time.monotonic() - started
                if response.status_code == 200:
                    try:
                        items = response.json().get("items", [])
                    except ValueError:
                        last_error = MonitorError("YouTube API: resposta inválida")
                    else:
                        return {item["id"]: item for item in items}, latency, 200
                else:
                    reason, message = self._error(response)
                    if reason in {"quotaExceeded", "dailyLimitExceeded"}:
                        raise QuotaExceeded(f"YouTube API: quota diária esgotada ({message})")
                    last_error = MonitorError(f"YouTube API HTTP {response.status_code}: {reason}: {message}")
                    retryable = response.status_code in {429, 500, 502, 503, 504} or reason in {
                        "rateLimitExceeded", "userRateLimitExceeded", "backendError"}
                    if not retryable:
                        raise last_error
            if attempt < self.retries:
                time.sleep(min(2**attempt, 5))
        raise last_error or MonitorError("YouTube API: falha desconhecida")

    @staticmethod
    def _error(response: requests.Response) -> tuple[str, str]:
        try:
            error = response.json().get("error", {})
            reason = (error.get("errors") or [{}])[0].get("reason") or error.get("status") or "erro"
            return str(reason), sanitize(str(error.get("message") or ""))
        except (ValueError, AttributeError, IndexError):
            return "resposta inválida", ""


def sanitize(text: str) -> str:
    return re.sub(r"(key=)[^&\s]+", r"\1***", text)


def normalize(video_id: str, item: dict[str, Any], latency: float, api_status: int, now: float) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    details = item.get("liveStreamingDetails", {})
    broadcast = snippet.get("liveBroadcastContent")
    if details.get("actualEndTime"):
        state = "ended"
    elif broadcast == "live":
        state = "live"
    elif broadcast == "upcoming":
        state = "scheduled"
    elif broadcast == "none" and details.get("actualStartTime"):
        state = "ended"
    elif details.get("actualStartTime"):
        state = "live"
    elif details.get("scheduledStartTime"):
        state = "scheduled"
    else:
        state = "unknown"

    def integer(source: dict[str, Any], key: str) -> int | None:
        value = source.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "channel_name": snippet.get("channelTitle", ""),
        "channel_id": snippet.get("channelId", ""),
        "concurrent_viewers": integer(details, "concurrentViewers") if state == "live" else None,
        "viewer_count_available": int(details.get("concurrentViewers") is not None),
        "total_views": integer(statistics, "viewCount"),
        "like_count": integer(statistics, "likeCount"),
        "comment_count": integer(statistics, "commentCount"),
        "status": STATUS[state],
        "scheduled_start": details.get("scheduledStartTime", ""),
        "scheduled_end": details.get("scheduledEndTime", ""),
        "actual_start": details.get("actualStartTime", ""),
        "actual_end": details.get("actualEndTime", ""),
        "last_update": int(now),
        "api_latency": round(latency, 3),
        "api_status": api_status,
    }


def api_state_snapshot(video_id: str, item: dict[str, Any], info: dict[str, Any],
                       previous_status: int | None = None) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    details = item.get("liveStreamingDetails", {})
    current_status = int(info["status"])
    return {
        "video_id": video_id,
        "status_anterior": previous_status,
        "status_normalizado": current_status,
        "status_nome": STATUS_NAMES.get(current_status, "unknown"),
        "liveBroadcastContent": snippet.get("liveBroadcastContent"),
        "scheduledStartTime": details.get("scheduledStartTime"),
        "actualStartTime": details.get("actualStartTime"),
        "actualEndTime": details.get("actualEndTime"),
        "concurrentViewers": details.get("concurrentViewers"),
    }


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def enabled_video_ids(cfg: dict[str, Any]) -> list[str]:
    return [live["video_id"] for live in cfg.get("lives", []) if live.get("enabled", True)]


_missing_key_reported = threading.Event()


def cycle(cfg: dict[str, Any], state: State, client: YouTubeClient, *, test: bool = False,
          inspect_api: bool = False, now: float | None = None) -> int:
    """Consulta as lives devidas. Devolve a quantidade de falhas."""
    now = time.time() if now is None else now
    collector_cfg = cfg["collector"]
    video_ids = enabled_video_ids(cfg)
    api_key = resolve_api_key(cfg)
    if not api_key:
        if not _missing_key_reported.is_set():
            logging.error("Chave da YouTube API ausente; consultas suspensas até o arquivo ser criado")
            _missing_key_reported.set()
        return len(video_ids) if test else 0
    if _missing_key_reported.is_set():
        logging.info("Chave da YouTube API encontrada; consultas retomadas")
        _missing_key_reported.clear()
    if not test and state.counter("quota_paused_until") > now:
        logging.debug("Quota esgotada; consultas pausadas até o reset")
        return 0

    due = video_ids if test else [video_id for video_id in video_ids if state.is_due(video_id, now)]
    if not test:
        skipped = sum(state.is_adaptively_deferred(video_id, now) for video_id in video_ids)
        if skipped:
            state.increment("scheduled_polls_skipped", skipped, now)

    calls_before = client.request_count
    failures = polled = 0
    for batch in chunks(due, int(collector_cfg["batch_size"])):
        if not test:
            for video_id in batch:
                state.mark_attempt(video_id, now)
        try:
            items, latency, api_status = client.get_many(batch, api_key)
        except QuotaExceeded as exc:
            reset = next_quota_reset(now) + 120
            logging.error("%s; pausando até %s", exc, datetime.fromtimestamp(reset, timezone.utc).isoformat())
            if not test:
                state.set_value("quota_paused_until", reset, now)
            failures += len(batch)
            break
        except Exception as exc:  # cada ID recebe seu próprio backoff persistente
            logging.error("Falha ao consultar lote de %d live(s): %s", len(batch), sanitize(str(exc)))
            failures += len(batch)
            if not test:
                for video_id in batch:
                    state.mark_failure(video_id, collector_cfg, now)
            continue
        polled += len(batch)
        for video_id in batch:
            item = items.get(video_id)
            if item is None:
                if test:
                    failures += 1
                    print(f"INDISPONÍVEL video_id={video_id} (privado, removido ou ID errado)")
                elif state.mark_unavailable(video_id, collector_cfg, now):
                    logging.warning("Vídeo indisponível (privado ou removido): %s", video_id)
                continue
            info = normalize(video_id, item, latency, api_status, now)
            if test:
                if inspect_api:
                    print(json.dumps(api_state_snapshot(video_id, item, info), ensure_ascii=False, indent=2))
                else:
                    print(f"OK video_id={video_id} título={info['title']!r} canal={info['channel_name']!r} "
                          f"status={STATUS_NAMES[info['status']]} api={api_status}")
                continue
            previous_status = state.last_status(video_id)
            if collector_cfg["log_api_state"] or previous_status != int(info["status"]):
                logging.info("Estado YouTube: %s", json.dumps(
                    api_state_snapshot(video_id, item, info, previous_status),
                    ensure_ascii=False, separators=(",", ":")))
            state.update(video_id, info, collector_cfg, now)
            state.mark_success(video_id, info, collector_cfg, now)

    if not test:
        state.record_api_calls(client.request_count - calls_before, polled, now)
        state.set_value("last_cycle_at", now, now)
        state.db.commit()
        logging.debug("Ciclo: habilitadas=%d consultadas=%d chamadas_api=%d falhas=%d",
                      len(video_ids), len(due), client.request_count - calls_before, failures)
    return failures


# ------------------------------------------------------------------ exporter
def _escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: dict[str, Any]) -> str:
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels.items()) + "}"


def _number(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return repr(int(number)) if number.is_integer() and abs(number) < 2**53 else repr(number)


def live_display_name(snapshot: dict[str, Any], tz: ZoneInfo) -> str:
    title = str(snapshot.get("title") or snapshot["video_id"]).replace('"', "'")
    source = parse_iso(snapshot.get("scheduled_start")) or parse_iso(snapshot.get("actual_start"))
    return f"{title} — {datetime.fromtimestamp(source, tz):%d/%m/%Y}" if source else title


def render_metrics(cfg: dict[str, Any], state: State, now: float) -> str:
    tz = ZoneInfo(cfg["display_timezone"])
    video_ids = enabled_video_ids(cfg)
    out: list[str] = []

    def family(name: str, help_text: str, kind: str, samples: list[tuple[dict[str, Any], Any]]) -> None:
        lines = [f"{name}{_labels(labels) if labels else ''} {text}"
                 for labels, value in samples if (text := _number(value)) is not None]
        if lines:
            out.extend([f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", *lines])

    snapshots = []
    for video_id in video_ids:
        snapshot = state.snapshot(video_id) or {"video_id": video_id, "status": STATUS["unknown"]}
        snapshot.setdefault("status", state.last_status(video_id) or STATUS["unknown"])
        status = int(snapshot.get("status") or 0)
        scheduled = parse_iso(snapshot.get("scheduled_start"))
        actual = parse_iso(snapshot.get("actual_start"))
        actual_end = parse_iso(snapshot.get("actual_end"))
        snapshot["elapsed_seconds"] = (
            max(0, int((actual_end or now) - actual)) if actual and status in {STATUS["live"], STATUS["ended"]}
            else None
        )
        snapshot["seconds_until_start"] = (
            max(0, int(scheduled - now)) if scheduled and status == STATUS["scheduled"] else None
        )
        snapshot["overdue_seconds"] = (
            max(0, int(now - scheduled)) if scheduled and status == STATUS["scheduled"] else None
        )
        if status != STATUS["live"]:
            for key in ("concurrent_viewers", "viewer_change_per_minute", "viewer_change_percent",
                        "new_views_per_minute", "likes_per_minute", "comments_per_minute"):
                snapshot[key] = None
        snapshots.append(snapshot)

    out.extend([
        "# HELP youtube_live_info Metadados da live (valor sempre 1)",
        "# TYPE youtube_live_info gauge",
    ])
    for snapshot in snapshots:
        labels = {
            "video_id": snapshot["video_id"],
            "channel_id": snapshot.get("channel_id") or "",
            "channel": snapshot.get("channel_name") or "desconhecido",
            "title": snapshot.get("title") or "",
            "live": live_display_name(snapshot, tz),
            "status_name": STATUS_NAMES.get(int(snapshot.get("status") or 0), "unknown"),
            "url": f"https://youtu.be/{snapshot['video_id']}",
        }
        out.append(f"youtube_live_info{_labels(labels)} 1")
    for name, (help_text, key) in LIVE_METRICS.items():
        family(name, help_text, "gauge", [({"video_id": s["video_id"]}, s.get(key)) for s in snapshots])

    health = state.health(video_ids, now)
    paused = health["quota_paused_until"] > now
    family("youtube_collector_info", "Versão do coletor", "gauge", [({"version": VERSION}, 1)])
    family("youtube_collector_api_calls_total", "Chamadas à YouTube Data API", "counter",
           [({}, health["api_calls_total"])])
    family("youtube_collector_videos_polled_total", "Vídeos consultados (somados entre chamadas)", "counter",
           [({}, health["videos_polled_total"])])
    family("youtube_collector_api_calls_today", "Chamadas no dia de quota (meia-noite do Pacífico)", "gauge",
           [({}, health["api_calls_today"])])
    family("youtube_collector_quota_daily_limit", "Quota diária configurada", "gauge",
           [({}, cfg["youtube"]["daily_quota"])])
    family("youtube_collector_quota_paused", "1 enquanto a quota esgotada pausa as consultas", "gauge",
           [({}, int(paused))])
    family("youtube_collector_scheduled_polls_skipped_total", "Consultas evitadas pela agenda adaptativa",
           "counter", [({}, health["scheduled_polls_skipped_total"])])
    family("youtube_collector_last_success_age_seconds", "Idade da última consulta bem-sucedida entre lives ativas",
           "gauge", [({}, health["last_success_age"])])
    family("youtube_collector_consecutive_errors", "Maior sequência de erros entre as lives", "gauge",
           [({}, health["consecutive_errors"])])
    family("youtube_collector_db_size_bytes", "Tamanho do banco SQLite", "gauge", [({}, health["db_size_bytes"])])
    family("youtube_collector_lives", "Lives habilitadas por estado", "gauge",
           [({"status": "enabled"}, len(video_ids))]
           + [({"status": name}, count) for name, count in health["lives"].items()])
    family("youtube_collector_api_key_configured", "1 se há chave da YouTube API", "gauge",
           [({}, int(bool(resolve_api_key(cfg))))])
    return "\n".join(out) + "\n"


class MetricsServer:
    def __init__(self, host: str, port: int):
        self._text = "# coletor iniciando\n"
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (nome exigido pela stdlib)
                if self.path.split("?", 1)[0] == "/metrics":
                    body = server.text.encode("utf-8")
                    content_type = "text/plain; version=0.0.4; charset=utf-8"
                elif self.path.split("?", 1)[0] in {"/", "/healthz"}:
                    body, content_type = b"ok\n", "text/plain; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        threading.Thread(target=self.httpd.serve_forever, name="metrics", daemon=True).start()

    @property
    def text(self) -> str:
        with self._lock:
            return self._text

    @text.setter
    def text(self, value: str) -> None:
        with self._lock:
            self._text = value


class ConfigWatcher:
    """Recarrega config e lives.yaml quando os arquivos mudam, sem reiniciar o serviço."""

    def __init__(self, path: str, cfg: dict[str, Any]):
        self.path = path
        self.cfg = cfg
        self.stamp = self._stamp(cfg)

    def _stamp(self, cfg: dict[str, Any]) -> tuple[float, ...]:
        stamps = []
        for candidate in (cfg["_config_path"], cfg.get("lives_file")):
            try:
                stamps.append(Path(candidate).stat().st_mtime if candidate else 0.0)
            except OSError:
                stamps.append(-1.0)
        return tuple(stamps)

    def poll(self) -> dict[str, Any]:
        stamp = self._stamp(self.cfg)
        if stamp != self.stamp:
            self.stamp = stamp
            try:
                cfg = load_config(self.path)
            except MonitorError as exc:
                logging.error("Configuração alterada é inválida; mantendo a anterior: %s", exc)
            else:
                logging.info("Configuração recarregada: %d live(s) habilitada(s)", len(enabled_video_ids(cfg)))
                self.cfg = cfg
                self.stamp = self._stamp(cfg)
        return self.cfg


def acquire_lock(database: str):
    lock_path = Path(f"{database}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise MonitorError(f"Outra instância do coletor já usa {database}") from exc
    return handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--check-config", action="store_true", help="Valida os arquivos sem acessar serviços externos")
    parser.add_argument("--test", action="store_true", help="Consulta todas as lives uma vez, sem gravar estado")
    parser.add_argument("--inspect-api", action="store_true", help="Mostra os campos de estado devolvidos pela API")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e imprime as métricas")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        cfg = load_config(args.config)
        if args.check_config:
            for warning in credential_warnings(cfg):
                print(f"AVISO: {warning}")
            print(f"Configuração válida: {len(enabled_video_ids(cfg))} live(s) habilitada(s), "
                  f"{len(cfg['lives'])} cadastrada(s)")
            return 0
        client = YouTubeClient(float(cfg["collector"]["timeout"]), int(cfg["collector"]["retries"]))
        if args.test or args.inspect_api:
            if credential_warnings(cfg):
                raise MonitorError(credential_warnings(cfg)[0])
            state = State(":memory:") if args.database == DEFAULT_DB else State(args.database)
            try:
                return 1 if cycle(cfg, state, client, test=True, inspect_api=args.inspect_api) else 0
            finally:
                state.close()
        lock = acquire_lock(args.database)
        state = State(args.database)
        try:
            if args.once:
                failures = cycle(cfg, state, client)
                sys.stdout.write(render_metrics(cfg, state, time.time()))
                return 1 if failures else 0
            exporter = cfg["exporter"]
            server = MetricsServer(str(exporter["listen"]), int(exporter["port"]))
            logging.info("Coletor %s: métricas em http://%s:%s/metrics, %d live(s) habilitada(s)",
                         VERSION, exporter["listen"], exporter["port"], len(enabled_video_ids(cfg)))
            for warning in credential_warnings(cfg):
                logging.warning(warning)
            watcher = ConfigWatcher(args.config, cfg)
            while True:
                loop_started = time.monotonic()
                cfg = watcher.poll()
                try:
                    cycle(cfg, state, client)
                except Exception as exc:
                    logging.error("Ciclo interrompido: %s", sanitize(str(exc)))
                    state.db.rollback()
                try:
                    server.text = render_metrics(cfg, state, time.time())
                except Exception as exc:
                    logging.error("Falha ao gerar métricas: %s", exc)
                interval = float(cfg["collector"]["interval"])
                time.sleep(max(0.0, interval - (time.monotonic() - loop_started)))
        finally:
            state.close()
            lock.close()
    except (MonitorError, OSError, ValueError, sqlite3.Error) as exc:
        logging.error("%s", sanitize(str(exc)))
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
